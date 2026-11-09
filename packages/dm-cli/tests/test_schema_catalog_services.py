"""Unit tests for the schema catalog application service and runner dispatch."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest

from db_cli_kit.profiles import ProfileName
from dm_cli.adapters.profile_store import JsonProfileStore
from dm_cli.application.profile import ProfileService
from dm_cli.application.results import InspectionCommandData
from dm_cli.application.runner import CliRuntime, execute_request
from dm_cli.application.schema_catalog import SchemaCatalogService
from dm_cli.domain.command import CommandAction, CommandGroup, CommandRequest, CommandStatus
from dm_cli.domain.profile import ProfileSetRequest, ProfileSettingsPatch
from dm_cli.ports.secret_store import SecretStore
from dm_client.domain.enums import ConstraintType, InspectionKind, ObjectType, SqlStatementType
from dm_client.domain.errors import InvalidArgumentError
from dm_client.domain.results import DdlResult, ExecutionMetadata, InspectionResult, QueryResult
from dm_client.domain.values import ObjectName, SchemaName, TableName
from dm_client.ports.driver import DriverColumn

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from dm_client.domain.configuration import DmConnectionConfig
    from dm_client.domain.values import DatabaseValue


@dataclass
class MemorySecretStore(SecretStore):
    """In-memory credential store; tests never touch the real keyring."""

    values: dict[ProfileName, str] = field(default_factory=dict)

    def get(self, name: ProfileName) -> str | None:
        return self.values.get(name)

    def set(self, name: ProfileName, password: str) -> None:
        self.values[name] = password

    def delete(self, name: ProfileName) -> None:
        self.values.pop(name, None)


@dataclass(frozen=True)
class QueryFixture:
    columns: tuple[DriverColumn, ...]
    rows: tuple[tuple[DatabaseValue, ...], ...]


def columns(*names: str) -> tuple[DriverColumn, ...]:
    return tuple(DriverColumn(name=name, type_name="VARCHAR") for name in names)


class FixtureCursor:
    def __init__(
        self,
        fixtures: dict[str, QueryFixture],
        executed: list[tuple[str, tuple[object, ...]]],
    ) -> None:
        self._fixtures = fixtures
        self._executed = executed
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
        self._executed.append((sql, tuple(parameters)))
        for marker, fixture in self._fixtures.items():
            if marker in sql:
                self._description = fixture.columns
                self._rows = list(fixture.rows)
                return
        raise AssertionError(f"unexpected query: {sql}")

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
    ) -> None:
        self._fixtures = fixtures
        self._executed = executed
        self.closed = False
        self.rollbacks = 0

    def cursor(self) -> FixtureCursor:
        return FixtureCursor(self._fixtures, self._executed)

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


def make_profiles(tmp_path: Path) -> ProfileService:
    profiles = ProfileService(
        JsonProfileStore(tmp_path / "profiles.json", lock_timeout=0.0),
        MemorySecretStore(),
        working_directory=tmp_path,
    )
    profiles.set(
        ProfileSetRequest(
            name=ProfileName(value="dev"),
            settings=ProfileSettingsPatch(host="127.0.0.1", port=15237, user="APP", schema="APP"),
            password="never-print-this",
        )
    )
    return profiles


def catalog_service(
    tmp_path: Path,
    fixtures: dict[str, QueryFixture],
) -> tuple[SchemaCatalogService, FakeFactory, list[tuple[str, tuple[object, ...]]]]:
    profiles = make_profiles(tmp_path)
    executed: list[tuple[str, tuple[object, ...]]] = []
    factory = FakeFactory(FakeConnection(fixtures, executed))
    return SchemaCatalogService(profiles, factory), factory, executed


def request_for(
    action: CommandAction,
    *,
    schema: SchemaName | None = None,
    table: TableName | None = None,
    object_type: ObjectType | None = None,
    object_name: ObjectName | None = None,
) -> CommandRequest:
    return CommandRequest(
        group=CommandGroup.SCHEMA,
        action=action,
        selected_profile=ProfileName(value="dev"),
        schema_name=schema,
        schema_table=table,
        schema_object_type=object_type,
        schema_object_name=object_name,
    )


def test_schema_ddl_service_returns_a_ddl_result_and_binds_the_object(tmp_path: Path) -> None:
    service, factory, executed = catalog_service(
        tmp_path,
        {
            "DBMS_METADATA.GET_DDL": QueryFixture(
                columns=columns("DDL"),
                rows=(("CREATE TABLE APP.T (ID INT)",),),
            )
        },
    )

    data = asyncio.run(
        service.execute(
            request_for(
                CommandAction.DDL,
                schema=SchemaName(value="APP"),
                object_type=ObjectType.TABLE,
                object_name=ObjectName(value="T"),
            )
        )
    )

    assert isinstance(data, InspectionCommandData)
    assert isinstance(data.result, DdlResult)
    assert data.command_group is CommandGroup.SCHEMA
    assert data.action is CommandAction.DDL
    assert data.profile == "dev"
    assert data.result.object_type is ObjectType.TABLE
    assert data.result.schema == "APP"
    assert data.result.name == "T"
    assert data.result.ddl == "CREATE TABLE APP.T (ID INT)"
    assert executed[-1][1] == ("TABLE", "T", "APP")
    assert factory.configs[0].schema == SchemaName(value="APP")


def test_schema_ddl_service_defaults_to_a_table_and_requires_a_name_before_connecting(
    tmp_path: Path,
) -> None:
    service, factory, executed = catalog_service(
        tmp_path,
        {
            "DBMS_METADATA.GET_DDL": QueryFixture(
                columns=columns("DDL"),
                rows=(("CREATE TABLE APP.T (ID INT)",),),
            )
        },
    )

    data = asyncio.run(
        service.execute(request_for(CommandAction.DDL, object_name=ObjectName(value="T")))
    )

    assert isinstance(data.result, DdlResult)
    assert data.result.object_type is ObjectType.TABLE
    assert executed[-1][1] == ("TABLE", "T", "APP")
    assert factory.configs[0].schema == SchemaName(value="APP")

    before = len(executed)
    with pytest.raises(InvalidArgumentError):
        asyncio.run(service.execute(request_for(CommandAction.DDL)))

    assert len(executed) == before


def test_schema_constraints_service_dispatches_the_table_and_schema(tmp_path: Path) -> None:
    service, _, executed = catalog_service(
        tmp_path,
        {
            "FROM ALL_CONSTRAINTS": QueryFixture(
                columns=columns(
                    "CONSTRAINT_NAME",
                    "CONSTRAINT_TYPE",
                    "TABLE_NAME",
                    "SEARCH_CONDITION",
                    "R_OWNER",
                    "R_CONSTRAINT_NAME",
                    "DELETE_RULE",
                    "STATUS",
                    "VALIDATED",
                ),
                rows=(("CK_T_ID", "C", "T", "ID > 0", None, None, None, "ENABLED", "VALIDATED"),),
            ),
            "FROM ALL_CONS_COLUMNS WHERE OWNER = ?": QueryFixture(
                columns=columns("OWNER", "CONSTRAINT_NAME", "TABLE_NAME", "COLUMN_NAME", "POSITION"),
                rows=(("APP", "CK_T_ID", "T", "ID", None),),
            ),
        },
    )

    data = asyncio.run(
        service.execute(
            request_for(
                CommandAction.CONSTRAINTS,
                schema=SchemaName(value="OTHER"),
                table=TableName(value="T"),
            )
        )
    )

    assert isinstance(data.result, InspectionResult)
    assert data.result.kind is InspectionKind.SCHEMA_CONSTRAINTS
    assert data.result.query.columns[0].name == "CONSTRAINT_NAME"
    assert data.result.query.rows[0].values[1] is ConstraintType.CHECK
    assert data.result.query.rows[0].values[3] == ["ID"]
    assert executed[-2][1] == ("OTHER", "T")
    assert "AND TABLE_NAME = ?" in executed[-2][0]


def test_schema_objects_service_dispatches_an_explicit_type(tmp_path: Path) -> None:
    service, _, executed = catalog_service(
        tmp_path,
        {
            "ALL_OBJECTS": QueryFixture(
                columns=columns("OBJECT_TYPE", "OBJECT_NAME", "STATUS", "CREATED", "LAST_DDL_TIME"),
                rows=(("INDEX", "IDX_T", "VALID", None, None),),
            )
        },
    )

    data = asyncio.run(
        service.execute(
            request_for(CommandAction.OBJECTS, object_type=ObjectType.INDEX)
        )
    )

    assert isinstance(data.result, InspectionResult)
    assert data.result.kind is InspectionKind.SCHEMA_OBJECTS
    assert [row.values for row in data.result.query.rows] == [("index", "IDX_T", "VALID", None, None)]
    assert executed[-1][1] == ("APP", "INDEX")


class RecordingExecutor:
    """Record which application service the runner dispatched to."""

    def __init__(self) -> None:
        self.calls: list[CommandRequest] = []

    async def execute(self, request: CommandRequest) -> InspectionCommandData:
        self.calls.append(request)
        return InspectionCommandData(
            status=CommandStatus.COMPLETED,
            command_group=request.group,
            action=request.action,
            profile="dev",
            result=InspectionResult(
                kind=InspectionKind.SCHEMA_TABLES,
                query=QueryResult(
                    columns=(),
                    rows=(),
                    metadata=ExecutionMetadata(statement_type=SqlStatementType.SELECT, duration_ms=0.0),
                ),
            ),
        )


def test_runner_dispatches_catalog_actions_to_the_catalog_service(tmp_path: Path) -> None:
    profiles = make_profiles(tmp_path)
    catalog = RecordingExecutor()
    inspection = RecordingExecutor()
    runtime = CliRuntime(
        profile_service=profiles,
        schema_inspection_service=inspection,
        schema_catalog_service=catalog,
    )

    for request in (
        request_for(CommandAction.DDL, object_name=ObjectName(value="T")),
        request_for(CommandAction.CONSTRAINTS),
        request_for(CommandAction.OBJECTS),
    ):
        asyncio.run(execute_request(runtime, request, stdin_text=None))

    asyncio.run(
        execute_request(
            runtime,
            request_for(CommandAction.TABLES),
            stdin_text=None,
        )
    )

    assert [call.action for call in catalog.calls] == [
        CommandAction.DDL,
        CommandAction.CONSTRAINTS,
        CommandAction.OBJECTS,
    ]
    assert [call.action for call in inspection.calls] == [CommandAction.TABLES]
