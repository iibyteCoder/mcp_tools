"""Unit tests for DM server and schema inspection execution."""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

import pytest

from dm_client.domain.configuration import DmConnectionConfig, SecretValue
from dm_client.domain.enums import KEY_SERVER_PARAMETERS, InspectionKind
from dm_client.domain.errors import ObjectNotFoundError
from dm_client.domain.requests import (
    SchemaDatabasesRequest,
    SchemaDescribeRequest,
    SchemaIndexesRequest,
    SchemaStatsRequest,
    SchemaTablesRequest,
    ServerCapabilitiesRequest,
    ServerInspectRequest,
    ServerParametersRequest,
)
from dm_client.domain.results import (
    DescribeResult,
    InspectionResult,
    ServerCapabilitiesResult,
    ServerInspectResult,
    TargetMetadata,
)
from dm_client.domain.values import SchemaName, TableName
from dm_client.execution.inspection import run_inspection
from dm_client.execution.session import DmSession
from dm_client.ports.driver import DriverColumn
from dm_client.sql.inspection_queries import SERVER_ALL_PARAMETERS_QUERY, SERVER_FILTERED_PARAMETERS_QUERY

if TYPE_CHECKING:
    from collections.abc import Sequence

    from dm_client.domain.values import DatabaseValue

INSTANCE_ROW: tuple[DatabaseValue, ...] = (
    "DM_NAME",
    "DM_NAME",
    "dm-host",
    "DM Database Server x64 V8",
    "DB Version: 0x7000d",
    datetime(2026, 11, 2, 10, 6, 2),
    "OPEN",
    "NORMAL",
    "03134284368-20250423-270902-20149",
    "Apr 23 2025 15:58:16",
)
INSTANCE_COLUMNS = (
    "NAME",
    "INSTANCE_NAME",
    "HOST_NAME",
    "SVR_VERSION",
    "DB_VERSION",
    "START_TIME",
    "STATUS$",
    "MODE$",
    "BUILD_VERSION",
    "BUILD_TIME",
)
TABLE_COLUMNS = (
    "SCHEMA_NAME",
    "TABLE_NAME",
    "TEMPORARY",
    "PARTITIONED",
    "NUM_ROWS",
    "LAST_ANALYZED",
)
COLUMN_COLUMNS = (
    "COLUMN_NAME",
    "DATA_TYPE",
    "DATA_LENGTH",
    "DATA_PRECISION",
    "DATA_SCALE",
    "NULLABLE",
    "DATA_DEFAULT",
    "COLUMN_ID",
    "COMMENT",
)
INDEX_COLUMNS = (
    "INDEX_NAME",
    "UNIQUENESS",
    "INDEX_TYPE",
    "COLUMN_NAME",
    "COLUMN_POSITION",
    "DESCEND",
    "STATUS",
)
STATS_COLUMNS = (
    "TABLE_NAME",
    "NUM_ROWS",
    "BLOCKS",
    "AVG_ROW_LEN",
    "SAMPLE_SIZE",
    "LAST_ANALYZED",
    "STALE_STATS",
)
PARAMETER_COLUMNS = (
    "PARA_NAME",
    "PARA_VALUE",
    "SESS_VALUE",
    "FILE_VALUE",
    "DEFAULT_VALUE",
    "MIN_VALUE",
    "MAX_VALUE",
    "REDACTED",
)


@dataclass(frozen=True)
class QueryFixture:
    """Rows and normalized columns returned for one scripted query."""

    columns: tuple[DriverColumn, ...]
    rows: tuple[tuple[DatabaseValue, ...], ...]


def columns(*names: str) -> tuple[DriverColumn, ...]:
    return tuple(DriverColumn(name=name, type_name="VARCHAR") for name in names)


class FakeCursor:
    def __init__(
        self,
        fixtures: dict[str, QueryFixture],
        executed: list[tuple[str, tuple[object, ...]]],
        threads: list[int],
    ) -> None:
        self._fixtures = fixtures
        self._executed = executed
        self._threads = threads
        self._description: Sequence[DriverColumn] | None = None
        self._rows: list[tuple[DatabaseValue, ...]] = []
        self.closed = False

    @property
    def description(self) -> Sequence[DriverColumn] | None:
        return self._description

    @property
    def rowcount(self) -> int:
        return len(self._rows)

    def execute(self, sql: str, parameters: tuple[object, ...] = ()) -> None:
        self._threads.append(threading.get_ident())
        self._executed.append((sql, tuple(parameters)))
        fixture = _fixture_for(sql, self._fixtures)
        self._description = fixture.columns
        self._rows = list(fixture.rows)

    def fetchmany(self, size: int) -> Sequence[Sequence[object]]:
        batch = self._rows[:size]
        self._rows = self._rows[size:]
        return batch

    def close(self) -> None:
        self.closed = True


class FakeConnection:
    user = "APP"
    server_version = "8.1.4.80"
    current_schema = "APP"
    str_case_sensitive = False
    max_identifier_length = 128

    def __init__(
        self,
        fixtures: dict[str, QueryFixture],
        executed: list[tuple[str, tuple[object, ...]]],
        threads: list[int],
    ) -> None:
        self._fixtures = fixtures
        self._executed = executed
        self._threads = threads
        self.closed = False
        self.rollbacks = 0

    def cursor(self) -> FakeCursor:
        return FakeCursor(self._fixtures, self._executed, self._threads)

    def explain(self, sql: str) -> str:
        return f"plan for {sql}"

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closed = True


class FakeFactory:
    def __init__(self, connection: FakeConnection) -> None:
        self._connection = connection
        self.configs: list[DmConnectionConfig] = []

    def connect(self, config: DmConnectionConfig) -> FakeConnection:
        self.configs.append(config)
        return self._connection


def connection_parts(
    fixtures: dict[str, QueryFixture],
) -> tuple[FakeConnection, list[tuple[str, tuple[object, ...]]], list[int]]:
    executed: list[tuple[str, tuple[object, ...]]] = []
    threads: list[int] = []
    return FakeConnection(fixtures, executed, threads), executed, threads


def _fixture_for(sql: str, fixtures: dict[str, QueryFixture]) -> QueryFixture:
    for marker, fixture in fixtures.items():
        if marker in sql:
            return fixture
    raise AssertionError(f"unexpected query: {sql}")


def test_server_inspect_reports_server_session_and_resolved_target() -> None:
    connection, executed, _ = connection_parts(
        {
            "V$INSTANCE": QueryFixture(
                columns=columns(*INSTANCE_COLUMNS),
                rows=(INSTANCE_ROW,),
            )
        }
    )

    result = run_inspection(connection, ServerInspectRequest(), "dev")

    assert isinstance(result, ServerInspectResult)
    assert result.server.name == "DM_NAME"
    assert result.server.instance_name == "DM_NAME"
    assert result.server.host_name == "dm-host"
    assert result.server.version == "DM Database Server x64 V8"
    assert result.server.db_version == "DB Version: 0x7000d"
    assert result.server.start_time == "2026-11-02T10:06:02"
    assert result.server.status == "OPEN"
    assert result.server.mode == "NORMAL"
    assert result.server.build_version == "03134284368-20250423-270902-20149"
    assert result.server.build_time == "Apr 23 2025 15:58:16"
    assert (result.session.user, result.session.schema) == ("APP", "APP")
    assert result.metadata.row_count == 1
    assert result.metadata.target == TargetMetadata(
        label="dev",
        schema="APP",
        server_version="8.1.4.80",
    )
    assert len(executed) == 1
    assert "FROM V$INSTANCE" in executed[0][0]


def test_server_capabilities_types_parameter_values_and_binds_names() -> None:
    connection, executed, _ = connection_parts(
        {
            "V$DM_INI": QueryFixture(
                columns=columns("PARA_NAME", "PARA_VALUE"),
                rows=(
                    ("COMPATIBLE_MODE", "4"),
                    ("CASE_SENSITIVE", "0"),
                    ("PAGE_SIZE", "8192"),
                    ("INSTANCE_NAME", "DM_NAME"),
                ),
            ),
            "V$VERSION": QueryFixture(
                columns=columns("BANNER"),
                rows=(("DM Database Server x64 V8",),),
            ),
        }
    )

    result = run_inspection(connection, ServerCapabilitiesRequest(), "dev")

    assert isinstance(result, ServerCapabilitiesResult)
    facts = {fact.name: fact for fact in result.facts}
    assert facts["compatible_mode"].value == 4
    assert facts["compatible_mode"].source == "V$DM_INI"
    assert facts["page_size"].value == 8192
    assert facts["instance_name"].value == "DM_NAME"
    assert facts["case_sensitive"].value is False
    assert facts["case_sensitive"].source == "dmPython"
    assert facts["max_identifier_length"].value == 128
    assert facts["max_identifier_length"].source == "dmPython"
    assert facts["server_version"].value == "8.1.4.80"
    assert facts["server_version"].source == "dmPython"
    assert facts["version_banners"].value == ["DM Database Server x64 V8"]
    assert result.metadata.row_count == len(result.facts)

    sql, parameters = executed[0]
    assert "V$DM_INI" in sql
    assert sql.count("?") == len(KEY_SERVER_PARAMETERS)
    assert "COMPATIBLE_MODE" not in sql
    assert parameters == tuple(key.value for key in KEY_SERVER_PARAMETERS)


def test_server_parameters_default_uses_key_names_and_redacts_sensitive_values() -> None:
    connection, executed, _ = connection_parts(
        {
            "V$DM_INI": QueryFixture(
                columns=columns(
                    "PARA_NAME",
                    "PARA_VALUE",
                    "SESS_VALUE",
                    "FILE_VALUE",
                    "DEFAULT_VALUE",
                    "MIN_VALUE",
                    "MAX_VALUE",
                ),
                rows=(
                    ("COMPATIBLE_MODE", "4", "4", "4", "4", "0", "10"),
                    ("PWD_POLICY", "2", "2", "2", "1", "0", "4"),
                    ("PASSWORD_VERIFICATION", "0", "0", "0", "0", "0", "1"),
                ),
            )
        }
    )

    result = run_inspection(connection, ServerParametersRequest(), "dev")

    assert isinstance(result, InspectionResult)
    assert result.kind is InspectionKind.SERVER_PARAMETERS
    assert [column.name for column in result.query.columns] == list(PARAMETER_COLUMNS)
    assert [row.values for row in result.query.rows] == [
        ("COMPATIBLE_MODE", "4", "4", "4", "4", "0", "10", False),
        ("PWD_POLICY", "***", "***", "***", "***", "***", "***", True),
        ("PASSWORD_VERIFICATION", "***", "***", "***", "***", "***", "***", True),
    ]
    assert result.query.metadata.row_count == 3
    sql, parameters = executed[0]
    assert sql.count("?") == len(KEY_SERVER_PARAMETERS)
    assert "ORDER BY PARA_NAME" in sql
    assert parameters == tuple(key.value for key in KEY_SERVER_PARAMETERS)


def test_server_parameters_filter_searches_all_names_case_insensitively() -> None:
    connection, executed, _ = connection_parts(
        {
            "V$DM_INI": QueryFixture(
                columns=columns(
                    "PARA_NAME",
                    "PARA_VALUE",
                    "SESS_VALUE",
                    "FILE_VALUE",
                    "DEFAULT_VALUE",
                    "MIN_VALUE",
                    "MAX_VALUE",
                ),
                rows=(("PWD_POLICY", "2", "2", "2", "1", "0", "4"),),
            )
        }
    )

    result = run_inspection(
        connection,
        ServerParametersRequest(name_filter="pwd", include_all=True),
        "dev",
    )

    assert isinstance(result, InspectionResult)
    assert result.kind is InspectionKind.SERVER_PARAMETERS
    assert [row.values for row in result.query.rows] == [
        ("PWD_POLICY", "***", "***", "***", "***", "***", "***", True),
    ]
    sql, parameters = executed[0]
    assert sql == SERVER_FILTERED_PARAMETERS_QUERY
    assert "INSTR(UPPER(PARA_NAME), UPPER(?))" in sql
    assert parameters == ("pwd",)
    assert sql.count("?") == 1


def test_server_parameters_all_returns_every_row_without_the_key_filter() -> None:
    connection, executed, _ = connection_parts(
        {
            "V$DM_INI": QueryFixture(
                columns=columns(
                    "PARA_NAME",
                    "PARA_VALUE",
                    "SESS_VALUE",
                    "FILE_VALUE",
                    "DEFAULT_VALUE",
                    "MIN_VALUE",
                    "MAX_VALUE",
                ),
                rows=(("BUFFER", 100, 100, 100, 100, None, None),),
            )
        }
    )

    result = run_inspection(connection, ServerParametersRequest(include_all=True), "dev")

    assert isinstance(result, InspectionResult)
    assert [row.values for row in result.query.rows] == [
        ("BUFFER", 100, 100, 100, 100, None, None, False),
    ]
    assert executed[0] == (SERVER_ALL_PARAMETERS_QUERY, ())


def test_schema_databases_hides_system_schemas_unless_all_is_requested() -> None:
    connection, _, _ = connection_parts(
        {
            "ALL_USERS": QueryFixture(
                columns=columns("USERNAME", "USER_ID"),
                rows=(("SYS", 0), ("APP", 5), ("SYSDBA", 1)),
            )
        }
    )

    default = run_inspection(connection, SchemaDatabasesRequest(), "dev")
    include_all = run_inspection(connection, SchemaDatabasesRequest(include_all=True), "dev")

    assert isinstance(default, InspectionResult)
    assert default.kind is InspectionKind.SCHEMA_DATABASES
    assert [column.name for column in default.query.columns] == [
        "SCHEMA_NAME",
        "USER_ID",
        "IS_SYSTEM",
    ]
    assert [row.values for row in default.query.rows] == [("APP", 5, False)]
    assert isinstance(default.query.rows[0].values[2], bool)
    assert isinstance(include_all, InspectionResult)
    assert [row.values for row in include_all.query.rows] == [
        ("SYS", 0, True),
        ("APP", 5, False),
        ("SYSDBA", 1, True),
    ]


def test_schema_tables_uses_effective_schema_and_binds_it() -> None:
    connection, executed, _ = connection_parts(
        {
            "ALL_TABLES": QueryFixture(
                columns=columns(*TABLE_COLUMNS),
                rows=(("APP", "A_TABLE", "N", "NO", 5, None),),
            )
        }
    )

    implicit = run_inspection(connection, SchemaTablesRequest(), "dev")
    explicit = run_inspection(
        connection,
        SchemaTablesRequest(schema=SchemaName(value="OTHER")),
        "dev",
    )

    assert isinstance(implicit, InspectionResult)
    assert implicit.kind is InspectionKind.SCHEMA_TABLES
    assert [column.name for column in implicit.query.columns] == list(TABLE_COLUMNS)
    assert [row.values for row in implicit.query.rows] == [("APP", "A_TABLE", "N", "NO", 5, None)]
    assert isinstance(explicit, InspectionResult)
    assert executed[0][1] == ("APP",)
    assert executed[1][1] == ("OTHER",)
    assert "?" in executed[0][0]
    assert "ORDER BY TABLE_NAME" in executed[0][0]


def test_schema_indexes_returns_one_row_per_column_with_exact_columns_and_binds() -> None:
    connection, executed, _ = connection_parts(
        {
            "ALL_INDEXES": QueryFixture(
                columns=columns(*INDEX_COLUMNS),
                rows=(
                    ("IDX_NAME", "UNIQUE", "NORMAL", "ID", 1, "ASC", "VALID"),
                    ("IDX_NAME", "UNIQUE", "NORMAL", "NAME", 2, "DESC", "VALID"),
                    ("IDX_OTHER", "NONUNIQUE", "NORMAL", "CODE", 1, "ASC", "INVALID"),
                ),
            )
        }
    )

    implicit = run_inspection(connection, SchemaIndexesRequest(table=TableName(value="T")), "dev")
    explicit = run_inspection(
        connection,
        SchemaIndexesRequest(table=TableName(value="T"), schema=SchemaName(value="OTHER")),
        "dev",
    )

    assert isinstance(implicit, InspectionResult)
    assert implicit.kind is InspectionKind.SCHEMA_INDEXES
    assert [column.name for column in implicit.query.columns] == list(INDEX_COLUMNS)
    assert [row.values for row in implicit.query.rows] == [
        ("IDX_NAME", "UNIQUE", "NORMAL", "ID", 1, "ASC", "VALID"),
        ("IDX_NAME", "UNIQUE", "NORMAL", "NAME", 2, "DESC", "VALID"),
        ("IDX_OTHER", "NONUNIQUE", "NORMAL", "CODE", 1, "ASC", "INVALID"),
    ]
    assert implicit.query.metadata.row_count == 3
    assert isinstance(explicit, InspectionResult)
    assert executed[0][1] == ("APP", "T")
    assert executed[1][1] == ("OTHER", "T")
    sql = executed[0][0]
    assert "FROM ALL_INDEXES" in sql
    assert "ALL_IND_COLUMNS" in sql
    assert "ORDER BY I.INDEX_NAME, C.COLUMN_POSITION" in sql


def test_schema_indexes_returns_zero_rows_when_the_table_has_no_indexes() -> None:
    connection, executed, _ = connection_parts(
        {
            "ALL_INDEXES": QueryFixture(
                columns=columns(*INDEX_COLUMNS),
                rows=(),
            )
        }
    )

    result = run_inspection(connection, SchemaIndexesRequest(table=TableName(value="T")), "dev")

    assert isinstance(result, InspectionResult)
    assert result.kind is InspectionKind.SCHEMA_INDEXES
    assert [column.name for column in result.query.columns] == list(INDEX_COLUMNS)
    assert result.query.rows == ()
    assert result.query.metadata.row_count == 0
    assert executed[0][1] == ("APP", "T")


def test_schema_stats_binds_schema_and_the_optional_table() -> None:
    connection, executed, _ = connection_parts(
        {
            "ALL_TAB_STATISTICS": QueryFixture(
                columns=columns(*STATS_COLUMNS),
                rows=(
                    ("A_TABLE", 10, 2, 40, 10, None, "NO"),
                    ("B_TABLE", 20, 4, 50, 20, None, "YES"),
                ),
            )
        }
    )

    implicit = run_inspection(connection, SchemaStatsRequest(), "dev")
    explicit = run_inspection(
        connection,
        SchemaStatsRequest(table=TableName(value="B_TABLE"), schema=SchemaName(value="OTHER")),
        "dev",
    )

    assert isinstance(implicit, InspectionResult)
    assert implicit.kind is InspectionKind.SCHEMA_STATS
    assert [column.name for column in implicit.query.columns] == list(STATS_COLUMNS)
    assert [row.values for row in implicit.query.rows] == [
        ("A_TABLE", 10, 2, 40, 10, None, "NO"),
        ("B_TABLE", 20, 4, 50, 20, None, "YES"),
    ]
    assert isinstance(explicit, InspectionResult)
    assert executed[0][1] == ("APP",)
    assert executed[1][1] == ("OTHER", "B_TABLE")
    assert "AND TABLE_NAME = ?" not in executed[0][0]
    assert "AND TABLE_NAME = ?" in executed[1][0]
    assert "ORDER BY TABLE_NAME" in executed[0][0]


def test_schema_stats_preserves_null_statistics_without_inventing_values() -> None:
    connection, _, _ = connection_parts(
        {
            "ALL_TAB_STATISTICS": QueryFixture(
                columns=columns(*STATS_COLUMNS),
                rows=(("A_TABLE", None, None, None, None, None, None),),
            )
        }
    )

    result = run_inspection(
        connection,
        SchemaStatsRequest(table=TableName(value="A_TABLE")),
        "dev",
    )

    assert isinstance(result, InspectionResult)
    assert result.kind is InspectionKind.SCHEMA_STATS
    assert [row.values for row in result.query.rows] == [
        ("A_TABLE", None, None, None, None, None, None),
    ]


def test_schema_stats_returns_zero_rows_when_statistics_are_absent() -> None:
    connection, _, _ = connection_parts(
        {
            "ALL_TAB_STATISTICS": QueryFixture(
                columns=columns(*STATS_COLUMNS),
                rows=(),
            )
        }
    )

    result = run_inspection(connection, SchemaStatsRequest(), "dev")

    assert isinstance(result, InspectionResult)
    assert result.kind is InspectionKind.SCHEMA_STATS
    assert [column.name for column in result.query.columns] == list(STATS_COLUMNS)
    assert result.query.rows == ()


def test_schema_describe_includes_column_comments_and_table_comment() -> None:
    connection, executed, _ = connection_parts(
        {
            "ALL_TAB_COLUMNS": QueryFixture(
                columns=columns(*COLUMN_COLUMNS),
                rows=(
                    ("ID", "INT", 4, None, None, "N", None, 1, "identifier"),
                    ("NAME", "VARCHAR", 50, None, None, "Y", None, 2, "display name"),
                ),
            ),
            "ALL_TAB_COMMENTS": QueryFixture(
                columns=columns("COMMENTS"),
                rows=(("Files",),),
            ),
        }
    )

    result = run_inspection(
        connection,
        SchemaDescribeRequest(table=TableName(value="T")),
        "dev",
    )

    assert isinstance(result, DescribeResult)
    assert result.table_comment == "Files"
    assert [column.name for column in result.query.columns] == list(COLUMN_COLUMNS)
    assert [row.values[-1] for row in result.query.rows] == ["identifier", "display name"]
    assert result.query.metadata.row_count == 2
    assert executed[0][1] == ("APP", "T")
    assert 'AS "COMMENT"' in executed[0][0]
    assert executed[1][1] == ("APP", "T")


def test_schema_describe_missing_table_raises_object_not_found() -> None:
    connection, executed, _ = connection_parts(
        {
            "ALL_TAB_COLUMNS": QueryFixture(
                columns=columns(*COLUMN_COLUMNS),
                rows=(),
            )
        }
    )

    with pytest.raises(ObjectNotFoundError, match=r"APP\.MISSING"):
        run_inspection(
            connection,
            SchemaDescribeRequest(table=TableName(value="MISSING")),
            "dev",
        )

    assert len(executed) == 1


def test_session_execute_inspection_uses_the_worker_thread_and_session_target() -> None:
    connection, _, threads = connection_parts(
        {
            "V$INSTANCE": QueryFixture(
                columns=columns(*INSTANCE_COLUMNS),
                rows=(INSTANCE_ROW,),
            )
        }
    )
    factory = FakeFactory(connection)
    config = DmConnectionConfig(
        host="127.0.0.1",
        port=15237,
        user="APP",
        password=SecretValue(_value="secret"),
        schema=SchemaName(value="APP"),
    )

    async def inspect() -> ServerInspectResult:
        async with DmSession(config, factory, "dev") as session:
            result = await session.execute_inspection(ServerInspectRequest())
        assert isinstance(result, ServerInspectResult)
        return result

    result = asyncio.run(inspect())

    assert result.metadata.target == TargetMetadata(
        label="dev",
        host="127.0.0.1",
        port=15237,
        schema="APP",
        server_version="8.1.4.80",
    )
    assert threads
    assert threads[0] != threading.get_ident()
    assert connection.closed is True
