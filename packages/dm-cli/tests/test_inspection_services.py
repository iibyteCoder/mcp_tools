"""Unit tests for the server and schema inspection application services."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest

from db_cli_kit.profiles import ProfileName
from dm_cli.adapters.profile_store import JsonProfileStore
from dm_cli.application.profile import ProfileService
from dm_cli.application.results import InspectionCommandData
from dm_cli.application.schema_inspection import SchemaInspectionService
from dm_cli.application.server_inspection import ServerInspectionService
from dm_cli.domain.command import CommandAction, CommandGroup, CommandRequest
from dm_cli.domain.profile import ProfileSetRequest, ProfileSettingsPatch
from dm_cli.ports.secret_store import SecretStore
from dm_client.domain.enums import InspectionKind
from dm_client.domain.errors import InvalidArgumentError
from dm_client.domain.results import (
    DescribeResult,
    InspectionResult,
    ServerCapabilitiesResult,
    ServerInspectResult,
)
from dm_client.domain.values import SchemaName, TableName
from dm_client.ports.driver import DriverColumn
from dm_client.sql.inspection_queries import SERVER_ALL_PARAMETERS_QUERY, SERVER_FILTERED_PARAMETERS_QUERY

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


def services(
    tmp_path: Path,
    fixtures: dict[str, QueryFixture],
) -> tuple[ServerInspectionService, SchemaInspectionService, FakeFactory, list[tuple[str, tuple[object, ...]]]]:
    profiles = make_profiles(tmp_path)
    executed: list[tuple[str, tuple[object, ...]]] = []
    connection = FakeConnection(fixtures, executed)
    factory = FakeFactory(connection)
    return (
        ServerInspectionService(profiles, factory),
        SchemaInspectionService(profiles, factory),
        factory,
        executed,
    )


def request_for(
    group: CommandGroup,
    action: CommandAction,
    *,
    schema: SchemaName | None = None,
    table: TableName | None = None,
    parameters_filter: str | None = None,
    parameters_include_all: bool = False,
) -> CommandRequest:
    return CommandRequest(
        group=group,
        action=action,
        selected_profile=ProfileName(value="dev"),
        schema_name=schema,
        schema_table=table,
        parameters_filter=parameters_filter,
        parameters_include_all=parameters_include_all,
    )


def test_server_inspect_service_returns_typed_result_and_closes_connection(tmp_path: Path) -> None:
    server_service, _, _, _ = services(
        tmp_path,
        {
            "V$INSTANCE": QueryFixture(
                columns=columns(
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
                ),
                rows=(
                    (
                        "DM",
                        "DM",
                        "host",
                        "DM V8",
                        "DB Version",
                        None,
                        "OPEN",
                        "NORMAL",
                        "build",
                        "time",
                    ),
                ),
            )
        },
    )

    data = asyncio.run(
        server_service.execute(request_for(CommandGroup.SERVER, CommandAction.INSPECT))
    )

    assert isinstance(data, InspectionCommandData)
    assert isinstance(data.result, ServerInspectResult)
    assert data.profile == "dev"
    assert data.command_group is CommandGroup.SERVER
    assert data.action is CommandAction.INSPECT
    assert data.result.server.name == "DM"
    assert data.result.session.user == "APP"


def test_server_capabilities_service_returns_typed_facts(tmp_path: Path) -> None:
    server_service, _, _, _ = services(
        tmp_path,
        {
            "V$DM_INI": QueryFixture(
                columns=columns("PARA_NAME", "PARA_VALUE"),
                rows=(("COMPATIBLE_MODE", "4"),),
            ),
            "V$VERSION": QueryFixture(columns=columns("BANNER"), rows=(("DM V8",),)),
        },
    )

    data = asyncio.run(
        server_service.execute(request_for(CommandGroup.SERVER, CommandAction.CAPABILITIES))
    )

    assert isinstance(data.result, ServerCapabilitiesResult)
    facts = {fact.name: fact for fact in data.result.facts}
    assert facts["compatible_mode"].value == 4
    assert facts["compatible_mode"].source == "V$DM_INI"
    assert facts["case_sensitive"].source == "dmPython"
    assert facts["server_version"].value == "8.1.4.80"


def test_server_parameters_service_dispatches_filter_all_and_redaction(tmp_path: Path) -> None:
    parameter_columns = (
        "PARA_NAME",
        "PARA_VALUE",
        "SESS_VALUE",
        "FILE_VALUE",
        "DEFAULT_VALUE",
        "MIN_VALUE",
        "MAX_VALUE",
    )
    server_service, _, _, executed = services(
        tmp_path,
        {
            "V$DM_INI": QueryFixture(
                columns=columns(*parameter_columns),
                rows=(
                    ("BUFFER", 100, 100, 100, 100, None, None),
                    ("PWD_POLICY", 2, 2, 2, 1, 0, 4),
                ),
            )
        },
    )

    everything = asyncio.run(
        server_service.execute(
            request_for(CommandGroup.SERVER, CommandAction.PARAMETERS, parameters_include_all=True)
        )
    )
    filtered = asyncio.run(
        server_service.execute(
            request_for(CommandGroup.SERVER, CommandAction.PARAMETERS, parameters_filter="PWD")
        )
    )

    assert isinstance(everything.result, InspectionResult)
    assert everything.result.kind is InspectionKind.SERVER_PARAMETERS
    assert [column.name for column in everything.result.query.columns] == [
        *parameter_columns,
        "REDACTED",
    ]
    assert [row.values for row in everything.result.query.rows] == [
        ("BUFFER", 100, 100, 100, 100, None, None, False),
        ("PWD_POLICY", "***", "***", "***", "***", "***", "***", True),
    ]
    assert executed[-2] == (SERVER_ALL_PARAMETERS_QUERY, ())
    assert isinstance(filtered.result, InspectionResult)
    assert [row.values[7] for row in filtered.result.query.rows] == [False, True]
    assert executed[-1] == (SERVER_FILTERED_PARAMETERS_QUERY, ("PWD",))


def test_schema_databases_service_uses_a_directory_binding(tmp_path: Path) -> None:
    profiles = make_profiles(tmp_path)
    profiles.bind(ProfileName(value="dev"), tmp_path)
    executed: list[tuple[str, tuple[object, ...]]] = []
    factory = FakeFactory(
        FakeConnection(
            {
                "ALL_USERS": QueryFixture(
                    columns=columns("USERNAME", "USER_ID"),
                    rows=(("SYS", 0), ("APP", 5)),
                )
            },
            executed,
        )
    )
    service = SchemaInspectionService(profiles, factory)

    data = asyncio.run(
        service.execute(CommandRequest(group=CommandGroup.SCHEMA, action=CommandAction.DATABASES))
    )

    assert isinstance(data.result, InspectionResult)
    assert data.profile == "dev"
    assert [row.values for row in data.result.query.rows] == [("APP", 5, False)]
    assert factory.configs[0].schema == SchemaName(value="APP")


def test_schema_tables_service_binds_the_explicit_schema(tmp_path: Path) -> None:
    _, schema_service, _, executed = services(
        tmp_path,
        {
            "ALL_TABLES": QueryFixture(
                columns=columns(
                    "SCHEMA_NAME",
                    "TABLE_NAME",
                    "TEMPORARY",
                    "PARTITIONED",
                    "NUM_ROWS",
                    "LAST_ANALYZED",
                ),
                rows=(("OTHER", "T", "N", "NO", 1, None),),
            )
        },
    )

    data = asyncio.run(
        schema_service.execute(
            request_for(
                CommandGroup.SCHEMA,
                CommandAction.TABLES,
                schema=SchemaName(value="OTHER"),
            )
        )
    )

    assert isinstance(data.result, InspectionResult)
    assert executed[-1][1] == ("OTHER",)
    assert "?" in executed[-1][0]


def test_schema_indexes_service_dispatches_the_table_and_schema(tmp_path: Path) -> None:
    _, schema_service, _, executed = services(
        tmp_path,
        {
            "ALL_INDEXES": QueryFixture(
                columns=columns(
                    "INDEX_NAME",
                    "UNIQUENESS",
                    "INDEX_TYPE",
                    "COLUMN_NAME",
                    "COLUMN_POSITION",
                    "DESCEND",
                    "STATUS",
                ),
                rows=(("IDX_NAME", "UNIQUE", "NORMAL", "ID", 1, "ASC", "VALID"),),
            )
        },
    )

    data = asyncio.run(
        schema_service.execute(
            request_for(
                CommandGroup.SCHEMA,
                CommandAction.INDEXES,
                schema=SchemaName(value="OTHER"),
                table=TableName(value="T"),
            )
        )
    )

    assert isinstance(data.result, InspectionResult)
    assert data.result.kind is InspectionKind.SCHEMA_INDEXES
    assert [column.name for column in data.result.query.columns] == [
        "INDEX_NAME",
        "UNIQUENESS",
        "INDEX_TYPE",
        "COLUMN_NAME",
        "COLUMN_POSITION",
        "DESCEND",
        "STATUS",
    ]
    assert [row.values for row in data.result.query.rows] == [
        ("IDX_NAME", "UNIQUE", "NORMAL", "ID", 1, "ASC", "VALID"),
    ]
    assert executed[-1][1] == ("OTHER", "T")


def test_schema_stats_service_accepts_an_optional_table(tmp_path: Path) -> None:
    _, schema_service, _, executed = services(
        tmp_path,
        {
            "ALL_TAB_STATISTICS": QueryFixture(
                columns=columns(
                    "TABLE_NAME",
                    "NUM_ROWS",
                    "BLOCKS",
                    "AVG_ROW_LEN",
                    "SAMPLE_SIZE",
                    "LAST_ANALYZED",
                    "STALE_STATS",
                ),
                rows=(("T", 10, 2, 40, 10, None, "NO"),),
            )
        },
    )

    without_table = asyncio.run(
        schema_service.execute(request_for(CommandGroup.SCHEMA, CommandAction.STATS))
    )
    with_table = asyncio.run(
        schema_service.execute(
            request_for(
                CommandGroup.SCHEMA,
                CommandAction.STATS,
                schema=SchemaName(value="OTHER"),
                table=TableName(value="T"),
            )
        )
    )

    assert isinstance(without_table.result, InspectionResult)
    assert without_table.result.kind is InspectionKind.SCHEMA_STATS
    assert [column.name for column in without_table.result.query.columns] == [
        "TABLE_NAME",
        "NUM_ROWS",
        "BLOCKS",
        "AVG_ROW_LEN",
        "SAMPLE_SIZE",
        "LAST_ANALYZED",
        "STALE_STATS",
    ]
    assert isinstance(with_table.result, InspectionResult)
    assert executed[-2][1] == ("APP",)
    assert executed[-1][1] == ("OTHER", "T")
    assert "AND TABLE_NAME = ?" not in executed[-2][0]
    assert "AND TABLE_NAME = ?" in executed[-1][0]


def test_schema_indexes_without_a_table_fails_before_connecting(tmp_path: Path) -> None:
    _, schema_service, factory, executed = services(tmp_path, {})

    with pytest.raises(InvalidArgumentError):
        asyncio.run(
            schema_service.execute(
                request_for(CommandGroup.SCHEMA, CommandAction.INDEXES)
            )
        )

    assert factory.configs == []
    assert executed == []


def test_schema_describe_service_returns_comments(tmp_path: Path) -> None:
    _, schema_service, _, executed = services(
        tmp_path,
        {
            "ALL_TAB_COLUMNS": QueryFixture(
                columns=columns(
                    "COLUMN_NAME",
                    "DATA_TYPE",
                    "DATA_LENGTH",
                    "DATA_PRECISION",
                    "DATA_SCALE",
                    "NULLABLE",
                    "DATA_DEFAULT",
                    "COLUMN_ID",
                    "COMMENT",
                ),
                rows=(("ID", "INT", 4, None, None, "N", None, 1, "identifier"),),
            ),
            "ALL_TAB_COMMENTS": QueryFixture(
                columns=columns("COMMENTS"),
                rows=(("Files",),),
            ),
        },
    )

    data = asyncio.run(
        schema_service.execute(
            request_for(
                CommandGroup.SCHEMA,
                CommandAction.DESCRIBE,
                schema=SchemaName(value="APP"),
                table=TableName(value="T"),
            )
        )
    )

    assert isinstance(data.result, DescribeResult)
    assert data.result.table_comment == "Files"
    assert data.result.query.columns[-1].name == "COMMENT"
    assert executed[-1][1] == ("APP", "T")


def test_schema_describe_without_a_table_fails_before_connecting(tmp_path: Path) -> None:
    _, schema_service, factory, executed = services(tmp_path, {})

    with pytest.raises(InvalidArgumentError):
        asyncio.run(
            schema_service.execute(
                request_for(CommandGroup.SCHEMA, CommandAction.DESCRIBE)
            )
        )

    assert factory.configs == []
    assert executed == []
