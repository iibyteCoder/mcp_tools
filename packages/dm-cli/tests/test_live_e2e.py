"""Live end-to-end checks against a local DM instance.

The test is skipped unless ``DB_DM_PASSWORD`` is present. Credentials are read
from the environment and never written to repository files or the profile
registry: the temporary store keeps only the secret-free profile settings.
"""

from __future__ import annotations

import asyncio
import os
import re
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from db_cli_kit.profiles import ProfileName
from dm_cli.adapters.profile_store import JsonProfileStore
from dm_cli.application.actual_plan import ActualPlanService
from dm_cli.application.input import LoadedInputs, ParameterDocument, load_inputs
from dm_cli.application.profile import ProfileService
from dm_cli.application.schema_catalog import SchemaCatalogService
from dm_cli.application.schema_inspection import SchemaInspectionService
from dm_cli.application.schema_maintenance import SchemaMaintenanceService
from dm_cli.application.server_inspection import ServerInspectionService
from dm_cli.application.sql import SqlExecutionService
from dm_cli.application.validation import DmSessionValidator
from dm_cli.domain.command import (
    CommandAction,
    CommandGroup,
    CommandRequest,
    ParameterKind,
    SqlInputSpec,
)
from dm_cli.domain.profile import ProfileSetRequest, ProfileSettingsPatch
from dm_cli.ports.secret_store import SecretStore
from dm_client.adapters import DisqlAutotraceRunner, DmpythonDriverFactory
from dm_client.domain.enums import (
    ComparisonDifferenceKind,
    ComparisonLocation,
    ConstraintType,
    InspectionKind,
    ObjectType,
    PlanParseStatus,
    TransactionAction,
    WriteOutcome,
)
from dm_client.domain.errors import ClientError, ComparisonError, UnsupportedSqlError
from dm_client.domain.requests import SqlInput
from dm_client.domain.results import (
    ActualPlanResult,
    AnalyzeResult,
    AnalyzeStatistics,
    BenchmarkResult,
    CompareResult,
    DdlResult,
    DescribeResult,
    ExplainResult,
    InspectionResult,
    QueryResult,
    ServerCapabilitiesResult,
    ServerInspectResult,
    WriteResult,
)
from dm_client.domain.values import ObjectName, TableName

if TYPE_CHECKING:
    from dm_cli.application.results import SqlCommandData
    from dm_client.domain.values import DatabaseValue

DB_DM_PASSWORD_ENV = "DB_DM_PASSWORD"
DBA_PASSWORD_ENV = "DB_DM_DBA_PASSWORD"
DISQL_PATH_ENV = "DB_DM_DISQL_PATH"
DBA_USER_ENV = "DB_DM_DBA_USER"
DBA_DEFAULT_USER = "DB_DM_DBA_TEST"
DBA_HOST = "localhost"
DBA_PORT = 5236
DBA_PROFILE_NAME = "dm-e2e-actual"
ACTUAL_PLAN_SQL = "SELECT * FROM AICA_FILE_INFO WHERE ROWNUM <= 3"
ACTUAL_PLAN_LINE_PATTERN = re.compile(r"^\s*\d+\s+#")
LIVE_HOST = "127.0.0.1"
LIVE_PORT = 15237
LIVE_USER = "TCA_REMIGRATION_20261026"
LIVE_SCHEMA = "TCA_REMIGRATION_20261026"
LIVE_PROFILE_NAME = "dm-e2e"
LIVE_TABLE = "AICA_FILE_INFO"
LIVE_VIEW = "AICA_KT_ACTIVITY_SCORE_VIEW"
LIVE_CONSTRAINT_TABLE = "ACIA_KT_SIMPLE_REPORT"
TEST_TABLE_PREFIX = "DB_DM_CLI_TEST_CLI_"
ANALYZE_TABLE_PREFIX = "DB_DM_CLI_TEST_ANALYZE_"
TEST_TABLE_PATTERN = "DB_DM_CLI_TEST_%"
PARAMS_SOURCE = Path("<live-e2e-params>")
QUERY_TIMEOUT_SECONDS = 30.0
LIVE_INDEX_COLUMNS = (
    "INDEX_NAME",
    "UNIQUENESS",
    "INDEX_TYPE",
    "COLUMN_NAME",
    "COLUMN_POSITION",
    "DESCEND",
    "STATUS",
)
LIVE_STATS_COLUMNS = (
    "TABLE_NAME",
    "NUM_ROWS",
    "BLOCKS",
    "AVG_ROW_LEN",
    "SAMPLE_SIZE",
    "LAST_ANALYZED",
    "STALE_STATS",
)
LIVE_CONSTRAINT_COLUMNS = (
    "CONSTRAINT_NAME",
    "CONSTRAINT_TYPE",
    "TABLE_NAME",
    "COLUMNS",
    "SEARCH_CONDITION",
    "REFERENCED_OWNER",
    "REFERENCED_TABLE",
    "REFERENCED_COLUMNS",
    "DELETE_RULE",
    "STATUS",
    "VALIDATED",
)
LIVE_OBJECT_COLUMNS = (
    "OBJECT_TYPE",
    "OBJECT_NAME",
    "STATUS",
    "CREATED",
    "LAST_DDL_TIME",
)
LIVE_PARAMETER_COLUMNS = (
    "PARA_NAME",
    "PARA_VALUE",
    "SESS_VALUE",
    "FILE_VALUE",
    "DEFAULT_VALUE",
    "MIN_VALUE",
    "MAX_VALUE",
    "REDACTED",
)

pytestmark = pytest.mark.skipif(
    not os.environ.get(DB_DM_PASSWORD_ENV),
    reason=f"{DB_DM_PASSWORD_ENV} is not set",
)


@dataclass
class MemorySecretStore(SecretStore):
    """In-memory credential store; the real keyring is never touched."""

    values: dict[ProfileName, str] = field(default_factory=dict)

    def get(self, name: ProfileName) -> str | None:
        return self.values.get(name)

    def set(self, name: ProfileName, password: str) -> None:
        self.values[name] = password

    def delete(self, name: ProfileName) -> None:
        self.values.pop(name, None)


def request_for(
    action: CommandAction,
    sql: str,
    *,
    transaction: TransactionAction = TransactionAction.COMMIT,
) -> CommandRequest:
    return CommandRequest(
        group=CommandGroup.SQL,
        action=action,
        selected_profile=ProfileName(value=LIVE_PROFILE_NAME),
        sql_input=SqlInputSpec.inline(sql),
        sql_transaction=transaction,
    )


def inputs_for(sql: str, parameters: tuple[DatabaseValue, ...] = ()) -> LoadedInputs:
    document = None
    if parameters:
        document = ParameterDocument(
            kind=ParameterKind.ARRAY,
            bindings=parameters,
            source=PARAMS_SOURCE,
        )
    return LoadedInputs(sql=SqlInput.inline(sql), parameters=document)


def inspection_request(
    group: CommandGroup,
    action: CommandAction,
    *,
    table: TableName | None = None,
    object_type: ObjectType | None = None,
    object_name: ObjectName | None = None,
    parameters_filter: str | None = None,
    parameters_include_all: bool = False,
) -> CommandRequest:
    return CommandRequest(
        group=group,
        action=action,
        selected_profile=ProfileName(value=LIVE_PROFILE_NAME),
        schema_table=table,
        schema_object_type=object_type,
        schema_object_name=object_name,
        parameters_filter=parameters_filter,
        parameters_include_all=parameters_include_all,
    )


def analyze_request(table: str) -> CommandRequest:
    return CommandRequest(
        group=CommandGroup.SCHEMA,
        action=CommandAction.ANALYZE,
        selected_profile=ProfileName(value=LIVE_PROFILE_NAME),
        schema_table=TableName(value=table),
    )


def execute(
    service: SqlExecutionService,
    action: CommandAction,
    sql: str,
    *,
    parameters: tuple[DatabaseValue, ...] = (),
    transaction: TransactionAction = TransactionAction.COMMIT,
) -> SqlCommandData:
    request = request_for(action, sql, transaction=transaction)
    return asyncio.run(service.execute(request, inputs_for(sql, parameters)))


def compare_request_for(
    left_sql: str,
    right_sql: str,
    *,
    key_columns: tuple[str, ...] = (),
) -> CommandRequest:
    return CommandRequest(
        group=CommandGroup.SQL,
        action=CommandAction.COMPARE,
        selected_profile=ProfileName(value=LIVE_PROFILE_NAME),
        compare_left_sql_input=SqlInputSpec.inline(left_sql),
        compare_right_sql_input=SqlInputSpec.inline(right_sql),
        compare_key_columns=key_columns,
    )


def create_profile_service(tmp_path: Path, factory: DmpythonDriverFactory) -> ProfileService:
    """Register the live profile in an isolated registry and in-memory keyring."""

    password = os.environ[DB_DM_PASSWORD_ENV]
    profiles = ProfileService(
        JsonProfileStore(tmp_path / "profiles.json", lock_timeout=0.0),
        MemorySecretStore(),
        DmSessionValidator(factory),
        working_directory=tmp_path,
    )
    profiles.set(
        ProfileSetRequest(
            name=ProfileName(value=LIVE_PROFILE_NAME),
            settings=ProfileSettingsPatch(
                host=LIVE_HOST,
                port=LIVE_PORT,
                user=LIVE_USER,
                schema=LIVE_SCHEMA,
                query_timeout=QUERY_TIMEOUT_SECONDS,
            ),
            password=password,
        )
    )
    return profiles


def create_dba_profile_service(tmp_path: Path) -> ProfileService:
    """Register the DBA profile in an isolated registry and in-memory keyring."""

    profiles = ProfileService(
        JsonProfileStore(tmp_path / "actual-profiles.json", lock_timeout=0.0),
        MemorySecretStore(),
        working_directory=tmp_path,
    )
    profiles.set(
        ProfileSetRequest(
            name=ProfileName(value=DBA_PROFILE_NAME),
            settings=ProfileSettingsPatch(
                host=DBA_HOST,
                port=DBA_PORT,
                user=os.environ.get(DBA_USER_ENV) or DBA_DEFAULT_USER,
                schema=LIVE_SCHEMA,
                query_timeout=QUERY_TIMEOUT_SECONDS,
            ),
            password=os.environ[DBA_PASSWORD_ENV],
        )
    )
    return profiles


def actual_plan_request(sql: str) -> CommandRequest:
    return CommandRequest(
        group=CommandGroup.SQL,
        action=CommandAction.EXPLAIN,
        selected_profile=ProfileName(value=DBA_PROFILE_NAME),
        sql_input=SqlInputSpec.inline(sql),
        sql_explain_actual=True,
    )


def test_live_profile_validate_write_read_rollback_and_cleanup(tmp_path: Path) -> None:
    factory = DmpythonDriverFactory()
    profiles = create_profile_service(tmp_path, factory)
    profile_name = ProfileName(value=LIVE_PROFILE_NAME)

    asyncio.run(profiles.validate(profile_name))

    service = SqlExecutionService(profiles, factory)
    table = f"{TEST_TABLE_PREFIX}{uuid4().hex[:8].upper()}"
    created = False
    try:
        created_result = execute(
            service,
            CommandAction.WRITE,
            f"CREATE TABLE {table} (ID INT, NAME VARCHAR(50))",
        )
        created = True
        assert isinstance(created_result.result, WriteResult)
        assert created_result.result.outcome is WriteOutcome.COMMITTED
        assert created_result.result.ddl_auto_commit is True

        inserted = execute(
            service,
            CommandAction.WRITE,
            f"INSERT INTO {table} (ID, NAME) VALUES (?, ?)",
            parameters=(1, "alpha"),
        )
        assert isinstance(inserted.result, WriteResult)
        assert inserted.result.outcome is WriteOutcome.COMMITTED
        assert inserted.result.affected_rows == 1

        selected = execute(
            service,
            CommandAction.READ,
            f"SELECT ID, NAME FROM {table} WHERE ID = ?",
            parameters=(1,),
        )
        assert isinstance(selected.result, QueryResult)
        assert [row.values for row in selected.result.rows] == [(1, "alpha")]

        rolled_back = execute(
            service,
            CommandAction.WRITE,
            f"INSERT INTO {table} (ID, NAME) VALUES (?, ?)",
            parameters=(2, "beta"),
            transaction=TransactionAction.ROLLBACK,
        )
        assert isinstance(rolled_back.result, WriteResult)
        assert rolled_back.result.outcome is WriteOutcome.ROLLED_BACK

        absent = execute(
            service,
            CommandAction.READ,
            f"SELECT ID FROM {table} WHERE ID = ?",
            parameters=(2,),
        )
        assert isinstance(absent.result, QueryResult)
        assert absent.result.rows == ()
    finally:
        if created:
            with suppress(ClientError):
                execute(service, CommandAction.WRITE, f"DROP TABLE {table}")

    leftovers = execute(
        service,
        CommandAction.READ,
        "SELECT TABLE_NAME FROM ALL_TABLES WHERE OWNER = ? AND TABLE_NAME LIKE ?",
        parameters=(LIVE_SCHEMA, f"{TEST_TABLE_PREFIX}%"),
    )
    assert isinstance(leftovers.result, QueryResult)
    assert leftovers.result.rows == ()


def live_service(tmp_path: Path) -> SqlExecutionService:
    factory = DmpythonDriverFactory()
    return SqlExecutionService(create_profile_service(tmp_path, factory), factory)


def test_live_explain_reports_plan_nodes_and_target(tmp_path: Path) -> None:
    service = live_service(tmp_path)

    data = execute(service, CommandAction.EXPLAIN, "SELECT 1 AS N FROM DUAL")

    assert isinstance(data.result, ExplainResult)
    assert data.action is CommandAction.EXPLAIN
    assert data.result.plan_text.strip()
    assert data.result.nodes
    assert data.result.parse_status in {PlanParseStatus.PARSED, PlanParseStatus.PARTIAL}
    target = data.result.metadata.target
    assert target is not None
    assert target.label == LIVE_PROFILE_NAME
    assert target.schema == LIVE_SCHEMA
    assert target.server_version


def test_live_explain_strips_a_leading_token_without_double_wrapping(tmp_path: Path) -> None:
    service = live_service(tmp_path)

    plain = execute(service, CommandAction.EXPLAIN, "SELECT 1 AS N FROM DUAL")
    prefixed = execute(service, CommandAction.EXPLAIN, "EXPLAIN SELECT 1 AS N FROM DUAL")

    assert isinstance(plain.result, ExplainResult)
    assert isinstance(prefixed.result, ExplainResult)
    assert prefixed.result.plan_text == plain.result.plan_text
    assert prefixed.result.nodes == plain.result.nodes


def test_live_explain_analyze_is_rejected(tmp_path: Path) -> None:
    service = live_service(tmp_path)

    with pytest.raises(UnsupportedSqlError):
        execute(service, CommandAction.EXPLAIN, "EXPLAIN ANALYZE SELECT 1 AS N FROM DUAL")


def test_live_explain_of_delete_does_not_change_rows(tmp_path: Path) -> None:
    service = live_service(tmp_path)
    table = f"{TEST_TABLE_PREFIX}{uuid4().hex[:8].upper()}"
    created = False
    try:
        execute(service, CommandAction.WRITE, f"CREATE TABLE {table} (ID INT)")
        created = True
        inserted = execute(
            service,
            CommandAction.WRITE,
            f"INSERT INTO {table} (ID) VALUES (?)",
            parameters=(1,),
        )
        assert isinstance(inserted.result, WriteResult)

        explained = execute(service, CommandAction.EXPLAIN, f"DELETE FROM {table} WHERE ID = 1")
        assert isinstance(explained.result, ExplainResult)
        assert explained.result.plan_text

        remaining = execute(service, CommandAction.READ, f"SELECT ID FROM {table} WHERE ID = 1")
        assert isinstance(remaining.result, QueryResult)
        assert len(remaining.result.rows) == 1
    finally:
        if created:
            with suppress(ClientError):
                execute(service, CommandAction.WRITE, f"DROP TABLE {table}")

    leftovers = execute(
        service,
        CommandAction.READ,
        "SELECT TABLE_NAME FROM ALL_TABLES WHERE OWNER = ? AND TABLE_NAME LIKE ?",
        parameters=(LIVE_SCHEMA, f"{TEST_TABLE_PREFIX}%"),
    )
    assert isinstance(leftovers.result, QueryResult)
    assert leftovers.result.rows == ()


def test_live_inspection_commands_report_server_schema_tables_and_columns(tmp_path: Path) -> None:
    factory = DmpythonDriverFactory()
    profiles = create_profile_service(tmp_path, factory)
    server_service = ServerInspectionService(profiles, factory)
    schema_service = SchemaInspectionService(profiles, factory)

    inspected = asyncio.run(
        server_service.execute(inspection_request(CommandGroup.SERVER, CommandAction.INSPECT))
    )
    assert isinstance(inspected.result, ServerInspectResult)
    assert inspected.result.server.name
    assert inspected.result.server.version
    assert inspected.result.session.user == LIVE_USER
    assert inspected.result.session.schema == LIVE_SCHEMA

    capabilities = asyncio.run(
        server_service.execute(inspection_request(CommandGroup.SERVER, CommandAction.CAPABILITIES))
    )
    assert isinstance(capabilities.result, ServerCapabilitiesResult)
    facts = {fact.name: fact for fact in capabilities.result.facts}
    assert facts["case_sensitive"].source == "dmPython"
    assert isinstance(facts["case_sensitive"].value, bool)
    assert isinstance(facts["max_identifier_length"].value, int)
    assert facts["server_version"].value
    assert any(fact.source == "V$DM_INI" for fact in capabilities.result.facts)

    databases = asyncio.run(
        schema_service.execute(inspection_request(CommandGroup.SCHEMA, CommandAction.DATABASES))
    )
    assert isinstance(databases.result, InspectionResult)
    assert databases.result.kind is InspectionKind.SCHEMA_DATABASES
    schema_names = [str(row.values[0]) for row in databases.result.query.rows]
    assert LIVE_SCHEMA in schema_names
    assert "SYS" not in schema_names
    assert all(isinstance(row.values[2], bool) for row in databases.result.query.rows)

    tables = asyncio.run(
        schema_service.execute(inspection_request(CommandGroup.SCHEMA, CommandAction.TABLES))
    )
    assert isinstance(tables.result, InspectionResult)
    assert [column.name for column in tables.result.query.columns] == [
        "SCHEMA_NAME",
        "TABLE_NAME",
        "TEMPORARY",
        "PARTITIONED",
        "NUM_ROWS",
        "LAST_ANALYZED",
    ]
    assert LIVE_TABLE in [str(row.values[1]) for row in tables.result.query.rows]

    described = asyncio.run(
        schema_service.execute(
            inspection_request(
                CommandGroup.SCHEMA,
                CommandAction.DESCRIBE,
                table=TableName(value=LIVE_TABLE),
            )
        )
    )
    assert isinstance(described.result, DescribeResult)
    assert described.result.query.columns[-1].name == "COMMENT"
    assert described.result.query.rows
    assert described.result.table_comment is None or isinstance(described.result.table_comment, str)


def test_live_schema_indexes_and_stats(tmp_path: Path) -> None:
    factory = DmpythonDriverFactory()
    profiles = create_profile_service(tmp_path, factory)
    schema_service = SchemaInspectionService(profiles, factory)

    indexes = asyncio.run(
        schema_service.execute(
            inspection_request(
                CommandGroup.SCHEMA,
                CommandAction.INDEXES,
                table=TableName(value=LIVE_TABLE),
            )
        )
    )
    assert isinstance(indexes.result, InspectionResult)
    assert indexes.result.kind is InspectionKind.SCHEMA_INDEXES
    assert [column.name for column in indexes.result.query.columns] == list(LIVE_INDEX_COLUMNS)
    assert indexes.result.query.rows
    index_names = sorted({str(row.values[0]) for row in indexes.result.query.rows})
    index_columns = [str(row.values[3]) for row in indexes.result.query.rows]
    print(f"{LIVE_TABLE} indexes: {index_names}; columns: {index_columns}")
    assert index_names
    assert all(index_columns)

    statistics = asyncio.run(
        schema_service.execute(inspection_request(CommandGroup.SCHEMA, CommandAction.STATS))
    )
    assert isinstance(statistics.result, InspectionResult)
    assert statistics.result.kind is InspectionKind.SCHEMA_STATS
    assert [column.name for column in statistics.result.query.columns] == list(LIVE_STATS_COLUMNS)
    assert statistics.result.query.rows
    print(f"statistics rows for {LIVE_SCHEMA}: {len(statistics.result.query.rows)}")

    filtered = asyncio.run(
        schema_service.execute(
            inspection_request(
                CommandGroup.SCHEMA,
                CommandAction.STATS,
                table=TableName(value=LIVE_TABLE),
            )
        )
    )
    assert isinstance(filtered.result, InspectionResult)
    assert filtered.result.kind is InspectionKind.SCHEMA_STATS
    assert [column.name for column in filtered.result.query.columns] == list(LIVE_STATS_COLUMNS)
    assert all(str(row.values[0]) == LIVE_TABLE for row in filtered.result.query.rows)

    service = SqlExecutionService(profiles, factory)
    leftovers = execute(
        service,
        CommandAction.READ,
        "SELECT TABLE_NAME FROM ALL_TABLES WHERE OWNER = ? AND TABLE_NAME LIKE ?",
        parameters=(LIVE_SCHEMA, f"{TEST_TABLE_PREFIX}%"),
    )
    assert isinstance(leftovers.result, QueryResult)
    assert leftovers.result.rows == ()


def test_live_schema_ddl_for_a_table_and_a_view(tmp_path: Path) -> None:
    factory = DmpythonDriverFactory()
    profiles = create_profile_service(tmp_path, factory)
    catalog_service = SchemaCatalogService(profiles, factory)

    table = asyncio.run(
        catalog_service.execute(
            inspection_request(
                CommandGroup.SCHEMA,
                CommandAction.DDL,
                object_type=ObjectType.TABLE,
                object_name=ObjectName(value=LIVE_TABLE),
            )
        )
    )
    assert isinstance(table.result, DdlResult)
    assert table.result.object_type is ObjectType.TABLE
    assert table.result.schema == LIVE_SCHEMA
    assert table.result.ddl.strip()
    print(f"{LIVE_TABLE} DDL length: {len(table.result.ddl)}")

    view = asyncio.run(
        catalog_service.execute(
            inspection_request(
                CommandGroup.SCHEMA,
                CommandAction.DDL,
                object_type=ObjectType.VIEW,
                object_name=ObjectName(value=LIVE_VIEW),
            )
        )
    )
    assert isinstance(view.result, DdlResult)
    assert view.result.object_type is ObjectType.VIEW
    assert view.result.ddl.strip()
    print(f"{LIVE_VIEW} DDL length: {len(view.result.ddl)}")


def test_live_schema_constraints_and_objects(tmp_path: Path) -> None:
    factory = DmpythonDriverFactory()
    profiles = create_profile_service(tmp_path, factory)
    catalog_service = SchemaCatalogService(profiles, factory)

    constraints = asyncio.run(
        catalog_service.execute(
            inspection_request(
                CommandGroup.SCHEMA,
                CommandAction.CONSTRAINTS,
                table=TableName(value=LIVE_CONSTRAINT_TABLE),
            )
        )
    )
    assert isinstance(constraints.result, InspectionResult)
    assert constraints.result.kind is InspectionKind.SCHEMA_CONSTRAINTS
    assert [column.name for column in constraints.result.query.columns] == list(LIVE_CONSTRAINT_COLUMNS)
    assert constraints.result.query.rows
    constraint_rows = [row.values for row in constraints.result.query.rows]
    assert all(str(values[2]) == LIVE_CONSTRAINT_TABLE for values in constraint_rows)
    assert all(isinstance(values[3], list) for values in constraint_rows)
    assert all(isinstance(values[7], list) for values in constraint_rows)
    checks = [values for values in constraint_rows if values[1] is ConstraintType.CHECK]
    assert checks
    assert any(values[3] for values in checks)
    print(
        f"{LIVE_CONSTRAINT_TABLE} constraints: "
        f"{[(str(values[0]), str(values[1])) for values in constraint_rows]}"
    )

    objects = asyncio.run(
        catalog_service.execute(inspection_request(CommandGroup.SCHEMA, CommandAction.OBJECTS))
    )
    assert isinstance(objects.result, InspectionResult)
    assert objects.result.kind is InspectionKind.SCHEMA_OBJECTS
    assert [column.name for column in objects.result.query.columns] == list(LIVE_OBJECT_COLUMNS)
    assert objects.result.query.rows
    object_pairs = {(str(row.values[0]), str(row.values[1])) for row in objects.result.query.rows}
    assert ("table", LIVE_TABLE) in object_pairs
    assert ("view", LIVE_VIEW) in object_pairs
    object_types = {object_type for object_type, _ in object_pairs}
    assert "index" not in object_types
    assert object_types <= {
        object_type.value for object_type in ObjectType if object_type is not ObjectType.INDEX
    }
    print(f"{LIVE_SCHEMA} default objects: {len(object_pairs)}")

    indexes = asyncio.run(
        catalog_service.execute(
            inspection_request(
                CommandGroup.SCHEMA,
                CommandAction.OBJECTS,
                object_type=ObjectType.INDEX,
            )
        )
    )
    assert isinstance(indexes.result, InspectionResult)
    assert indexes.result.kind is InspectionKind.SCHEMA_OBJECTS
    assert [column.name for column in indexes.result.query.columns] == list(LIVE_OBJECT_COLUMNS)
    assert indexes.result.query.rows
    assert all(str(row.values[0]) == "index" for row in indexes.result.query.rows)
    print(f"{LIVE_SCHEMA} indexes: {len(indexes.result.query.rows)}")

    service = SqlExecutionService(profiles, factory)
    leftovers = execute(
        service,
        CommandAction.READ,
        "SELECT TABLE_NAME FROM ALL_TABLES WHERE OWNER = ? AND TABLE_NAME LIKE ?",
        parameters=(LIVE_SCHEMA, f"{TEST_TABLE_PREFIX}%"),
    )
    assert isinstance(leftovers.result, QueryResult)
    assert leftovers.result.rows == ()


def test_live_server_parameters_redacts_filtered_values(tmp_path: Path) -> None:
    factory = DmpythonDriverFactory()
    profiles = create_profile_service(tmp_path, factory)
    server_service = ServerInspectionService(profiles, factory)

    parameters = asyncio.run(
        server_service.execute(
            inspection_request(CommandGroup.SERVER, CommandAction.PARAMETERS)
        )
    )
    assert isinstance(parameters.result, InspectionResult)
    assert parameters.result.kind is InspectionKind.SERVER_PARAMETERS
    assert [column.name for column in parameters.result.query.columns] == list(LIVE_PARAMETER_COLUMNS)
    assert parameters.result.query.rows
    assert all(isinstance(row.values[7], bool) for row in parameters.result.query.rows)
    assert all(row.values[7] is False for row in parameters.result.query.rows)
    print(
        f"default parameters: {[str(row.values[0]) for row in parameters.result.query.rows]}"
    )

    filtered = asyncio.run(
        server_service.execute(
            inspection_request(
                CommandGroup.SERVER,
                CommandAction.PARAMETERS,
                parameters_filter="PWD",
            )
        )
    )
    assert isinstance(filtered.result, InspectionResult)
    assert filtered.result.kind is InspectionKind.SERVER_PARAMETERS
    assert filtered.result.query.rows
    for row in filtered.result.query.rows:
        assert row.values[7] is True
        assert row.values[1:7] == ("***", "***", "***", "***", "***", "***")
    print(
        f"filtered parameters: {[str(row.values[0]) for row in filtered.result.query.rows]}"
    )


def test_live_schema_analyze_collects_statistics_and_cleans_up(tmp_path: Path) -> None:
    factory = DmpythonDriverFactory()
    profiles = create_profile_service(tmp_path, factory)
    sql_service = SqlExecutionService(profiles, factory)
    maintenance_service = SchemaMaintenanceService(profiles, factory)

    table = f"{ANALYZE_TABLE_PREFIX}{uuid4().hex[:8].upper()}"
    created = False
    try:
        created_result = execute(
            sql_service,
            CommandAction.WRITE,
            f"CREATE TABLE {table} (ID INT, NAME VARCHAR(50))",
        )
        created = True
        assert isinstance(created_result.result, WriteResult)

        for row_id, name in ((1, "alpha"), (2, "beta"), (3, "gamma")):
            inserted = execute(
                sql_service,
                CommandAction.WRITE,
                f"INSERT INTO {table} (ID, NAME) VALUES (?, ?)",
                parameters=(row_id, name),
            )
            assert isinstance(inserted.result, WriteResult)

        data = asyncio.run(maintenance_service.execute(analyze_request(table)))

        assert isinstance(data.result, AnalyzeResult)
        assert data.command_group is CommandGroup.SCHEMA
        assert data.action is CommandAction.ANALYZE
        assert data.profile == LIVE_PROFILE_NAME
        result = data.result
        assert result.schema == LIVE_SCHEMA
        assert result.table == table
        assert result.partition is None
        assert result.options.estimate_percent is None
        assert result.options.cascade is True
        assert result.options.degree is None
        assert result.outcome is WriteOutcome.COMMITTED
        assert isinstance(result.before, AnalyzeStatistics)
        assert result.before.num_rows is None or result.before.num_rows >= 0
        assert result.before.last_analyzed is None or isinstance(
            result.before.last_analyzed, datetime
        )
        assert result.after.last_analyzed is not None
        assert result.after.num_rows == 3
        print(f"{table} analyze: before={result.before} after={result.after}")
    finally:
        if created:
            with suppress(ClientError):
                execute(sql_service, CommandAction.WRITE, f"DROP TABLE {table}")

    leftovers = execute(
        sql_service,
        CommandAction.READ,
        "SELECT TABLE_NAME FROM ALL_TABLES WHERE OWNER = ? AND TABLE_NAME LIKE ?",
        parameters=(LIVE_SCHEMA, f"{ANALYZE_TABLE_PREFIX}%"),
    )
    assert isinstance(leftovers.result, QueryResult)
    assert leftovers.result.rows == ()


def test_live_benchmark_select_dual_reports_samples_without_writes(tmp_path: Path) -> None:
    service = live_service(tmp_path)
    sql = "SELECT 1 AS N FROM DUAL"
    request = CommandRequest(
        group=CommandGroup.SQL,
        action=CommandAction.BENCHMARK,
        selected_profile=ProfileName(value=LIVE_PROFILE_NAME),
        sql_input=SqlInputSpec.inline(sql),
        sql_iterations=2,
        sql_warmup_iterations=0,
    )

    data = asyncio.run(service.execute(request, inputs_for(sql)))

    assert isinstance(data.result, BenchmarkResult)
    assert data.action is CommandAction.BENCHMARK
    assert data.result.iterations == 2
    assert data.result.warmup_iterations == 0
    assert len(data.result.samples_ms) == 2
    assert all(isinstance(sample, float) and sample >= 0.0 for sample in data.result.samples_ms)
    assert data.result.minimum_ms == min(data.result.samples_ms)
    assert data.result.maximum_ms == max(data.result.samples_ms)
    assert data.result.minimum_ms <= data.result.average_ms <= data.result.maximum_ms
    assert data.result.minimum_ms <= data.result.median_ms <= data.result.maximum_ms
    assert data.result.metadata.target is not None
    assert data.result.metadata.target.label == LIVE_PROFILE_NAME
    assert data.result.metadata.target.schema == LIVE_SCHEMA
    print(
        f"benchmark samples_ms={data.result.samples_ms} "
        f"min={data.result.minimum_ms:.3f} median={data.result.median_ms:.3f}"
    )

    leftovers = execute(
        service,
        CommandAction.READ,
        "SELECT TABLE_NAME FROM ALL_TABLES WHERE OWNER = ? AND TABLE_NAME LIKE ?",
        parameters=(LIVE_SCHEMA, TEST_TABLE_PATTERN),
    )
    assert isinstance(leftovers.result, QueryResult)
    assert leftovers.result.rows == ()


def test_live_compare_equal_selects_return_equal(tmp_path: Path) -> None:
    service = live_service(tmp_path)
    request = compare_request_for("SELECT 1 AS ID FROM DUAL", "SELECT 1 AS ID FROM DUAL")

    data = asyncio.run(service.execute(request, load_inputs(request, stdin_text=None)))

    assert isinstance(data.result, CompareResult)
    assert data.action is CommandAction.COMPARE
    assert data.result.equal is True
    assert data.result.differences == ()
    assert data.result.left.row_count == 1
    assert data.result.right.row_count == 1
    assert [column.name for column in data.result.left.columns] == ["ID"]
    assert data.result.metadata is not None
    assert data.result.metadata.target is not None
    assert data.result.metadata.target.schema == LIVE_SCHEMA


def test_live_compare_unequal_selects_raise_comparison_error(tmp_path: Path) -> None:
    service = live_service(tmp_path)
    request = compare_request_for("SELECT 1 AS ID FROM DUAL", "SELECT 2 AS ID FROM DUAL")

    with pytest.raises(ComparisonError) as caught:
        asyncio.run(service.execute(request, load_inputs(request, stdin_text=None)))

    differences = caught.value.differences
    assert differences
    assert differences[0].kind is ComparisonDifferenceKind.ROW_VALUE
    assert differences[0].location is ComparisonLocation.ROW
    print(f"compare differences: {[(str(item.kind), str(item.location)) for item in differences]}")


def test_live_compare_keyed_equal_rows_are_equal(tmp_path: Path) -> None:
    service = live_service(tmp_path)
    sql = "SELECT 1 AS ID, 'a' AS V FROM DUAL"
    request = compare_request_for(sql, sql, key_columns=("ID",))

    data = asyncio.run(service.execute(request, load_inputs(request, stdin_text=None)))

    assert isinstance(data.result, CompareResult)
    assert data.result.equal is True
    assert data.result.differences == ()
    assert [column.name for column in data.result.right.columns] == ["ID", "V"]

    leftovers = execute(
        service,
        CommandAction.READ,
        "SELECT TABLE_NAME FROM ALL_TABLES WHERE OWNER = ? AND TABLE_NAME LIKE ?",
        parameters=(LIVE_SCHEMA, TEST_TABLE_PATTERN),
    )
    assert isinstance(leftovers.result, QueryResult)
    assert leftovers.result.rows == ()


@pytest.mark.skipif(
    not os.environ.get(DBA_PASSWORD_ENV) or not os.environ.get(DISQL_PATH_ENV),
    reason=f"{DBA_PASSWORD_ENV} and {DISQL_PATH_ENV} are not set",
)
def test_live_actual_plan_collects_estimate_and_actual_statistics(tmp_path: Path) -> None:
    profiles = create_dba_profile_service(tmp_path)
    service = ActualPlanService(
        profiles,
        DisqlAutotraceRunner(executable=os.environ[DISQL_PATH_ENV]),
    )
    request = actual_plan_request(ACTUAL_PLAN_SQL)

    data = asyncio.run(service.execute(request, load_inputs(request, stdin_text=None)))

    assert isinstance(data.result, ActualPlanResult)
    assert data.action is CommandAction.EXPLAIN
    assert data.profile == DBA_PROFILE_NAME
    result = data.result
    assert result.executed is True
    assert result.provider == "disql-autotrace"
    plan_lines = result.plan_text.splitlines()
    assert plan_lines
    assert ACTUAL_PLAN_LINE_PATTERN.match(plan_lines[0]) is not None
    statistics = {item.name: item.value for item in result.statistics}
    assert "logical_reads" in statistics
    assert "exec_time_ms" in statistics
    assert "Statistics" in result.autotrace_text
    assert result.metadata.target is not None
    assert result.metadata.target.label == DBA_PROFILE_NAME
    assert result.metadata.target.schema == LIVE_SCHEMA
    assert result.duration_ms >= 0.0
    print(f"actual plan statistics: {statistics}")

    update_request = actual_plan_request("UPDATE AICA_FILE_INFO SET NAME = 'x'")
    with pytest.raises(UnsupportedSqlError):
        asyncio.run(service.execute(update_request, load_inputs(update_request, stdin_text=None)))

    analyze_request = actual_plan_request("EXPLAIN ANALYZE SELECT * FROM AICA_FILE_INFO")
    with pytest.raises(UnsupportedSqlError):
        asyncio.run(service.execute(analyze_request, load_inputs(analyze_request, stdin_text=None)))
