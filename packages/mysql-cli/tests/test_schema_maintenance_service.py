from __future__ import annotations

import json
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from db_cli_kit.json_codec import encode_json_document
from db_cli_kit.profiles import ProfileName
from db_cli_kit.secrets import SecretStore
from mysql_cli.adapters.profile_store import JsonProfileStore
from mysql_cli.application.profile import ProfileService
from mysql_cli.application.schema_maintenance import SchemaMaintenanceService
from mysql_cli.domain.command import CommandAction, CommandGroup, CommandRequest, CommandStatus
from mysql_cli.domain.profile import ProfileSetRequest, ProfileSettingsPatch
from mysql_client import (
    DatabaseName,
    DriverColumn,
    DriverConnection,
    DriverCursor,
    ErrorCode,
    InvalidArgumentError,
    MySqlConnectionConfig,
    QueryExecutionError,
    TableName,
)
from mysql_client.ports.driver import DriverFailure, DriverFailureKind

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from mysql_client.domain.values import DatabaseParameters

ANALYZE_COLUMNS = (
    DriverColumn(name="Table", type_name="VARCHAR"),
    DriverColumn(name="Op", type_name="VARCHAR"),
    DriverColumn(name="Msg_type", type_name="VARCHAR"),
    DriverColumn(name="Msg_text", type_name="VARCHAR"),
)


@dataclass
class MemorySecretStore(SecretStore):
    values: dict[ProfileName, str]

    def get(self, name: ProfileName) -> str | None:
        return self.values.get(name)

    def set(self, name: ProfileName, password: str) -> None:
        self.values[name] = password

    def delete(self, name: ProfileName) -> None:
        self.values.pop(name, None)


class AnalyzeCursor:
    rowcount = 1
    lastrowid = None

    def __init__(
        self,
        columns: Sequence[DriverColumn],
        rows: Sequence[Sequence[object]],
        *,
        failure: DriverFailure | None = None,
    ) -> None:
        self.description = tuple(columns)
        self._rows = tuple(tuple(row) for row in rows)
        self._position = 0
        self._failure = failure
        self.executed: list[tuple[str, DatabaseParameters]] = []

    async def execute(self, sql: str, parameters: DatabaseParameters) -> None:
        self.executed.append((sql, parameters))
        if self._failure is not None:
            raise self._failure
        self._position = 0

    async def fetchmany(self, size: int) -> Sequence[Sequence[object]]:
        end = min(self._position + size, len(self._rows))
        rows = self._rows[self._position : end]
        self._position = end
        return rows


class AnalyzeCursorContext(AbstractAsyncContextManager[DriverCursor]):
    def __init__(self, cursor: AnalyzeCursor) -> None:
        self._cursor = cursor

    async def __aenter__(self) -> DriverCursor:
        return self._cursor

    async def __aexit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        del exc_type, exc_value, traceback


class AnalyzeConnection:
    thread_id = 29

    def __init__(self, cursor: AnalyzeCursor) -> None:
        self.cursor_value = cursor
        self.begin_count = 0
        self.commit_count = 0
        self.rollback_count = 0
        self.close_count = 0

    def cursor(self) -> AbstractAsyncContextManager[DriverCursor]:
        return AnalyzeCursorContext(self.cursor_value)

    async def begin(self) -> None:
        self.begin_count += 1

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        self.rollback_count += 1

    async def close(self) -> None:
        self.close_count += 1


class AnalyzeFactory:
    def __init__(self, connection: AnalyzeConnection) -> None:
        self.connection = connection
        self.configs: list[MySqlConnectionConfig] = []

    async def connect(self, config: MySqlConnectionConfig) -> DriverConnection:
        self.configs.append(config)
        return self.connection


def configured_profiles(tmp_path: Path) -> ProfileService:
    profiles = ProfileService(
        JsonProfileStore(tmp_path / "profiles.json"),
        MemorySecretStore({}),
        working_directory=tmp_path,
    )
    profiles.set(
        ProfileSetRequest(
            name=ProfileName(value="dev"),
            settings=ProfileSettingsPatch(host="db.example", user="alice"),
            password="do-not-output",
        )
    )
    return profiles


def analyze_request(
    *,
    action: CommandAction = CommandAction.ANALYZE,
    database: str | None = "billing",
    table: str | None = "invoices",
) -> CommandRequest:
    return CommandRequest(
        group=CommandGroup.SCHEMA,
        action=action,
        selected_profile=ProfileName(value="dev"),
        schema_database=None if database is None else DatabaseName(value=database),
        schema_table=None if table is None else TableName(value=table),
        schema_timeout_seconds=3.0,
    )


@pytest.mark.asyncio
async def test_schema_maintenance_service_resolves_profile_and_returns_envelope(tmp_path: Path) -> None:
    profiles = configured_profiles(tmp_path)
    cursor = AnalyzeCursor(ANALYZE_COLUMNS, (("billing.invoices", "analyze", "status", "OK"),))
    connection = AnalyzeConnection(cursor)
    factory = AnalyzeFactory(connection)

    data = await SchemaMaintenanceService(profiles, factory).execute(analyze_request())
    document = encode_json_document(data)
    payload = json.loads(document)

    assert data.status is CommandStatus.COMPLETED
    assert data.command_group is CommandGroup.SCHEMA
    assert data.action is CommandAction.ANALYZE
    assert data.profile == "dev"
    assert payload["result"]["rows"] == [
        {
            "table_name": "billing.invoices",
            "operation": "analyze",
            "message_type": "status",
            "message": "OK",
        }
    ]
    assert payload["result"]["metadata"]["statement_type"] == "ddl"
    assert "do-not-output" not in document
    assert factory.configs[0].host == "db.example"
    assert cursor.executed == [("ANALYZE TABLE `billing`.`invoices`", ())]
    assert connection.begin_count == 0
    assert connection.commit_count == 0
    assert connection.rollback_count == 0
    assert connection.close_count == 1


@pytest.mark.asyncio
async def test_schema_maintenance_service_maps_driver_failures_to_client_errors(tmp_path: Path) -> None:
    profiles = configured_profiles(tmp_path)
    cursor = AnalyzeCursor(
        ANALYZE_COLUMNS,
        (),
        failure=DriverFailure(DriverFailureKind.EXECUTION),
    )
    connection = AnalyzeConnection(cursor)

    service = SchemaMaintenanceService(profiles, AnalyzeFactory(connection))
    with pytest.raises(QueryExecutionError) as error:
        await service.execute(analyze_request())

    assert error.value.code is ErrorCode.QUERY_FAILED
    assert connection.begin_count == 0
    assert connection.commit_count == 0
    assert connection.rollback_count == 0
    assert connection.close_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "command_request",
    [
        analyze_request(action=CommandAction.STATS),
        analyze_request(table=None),
    ],
)
async def test_schema_maintenance_service_rejects_invalid_requests(
    tmp_path: Path,
    command_request: CommandRequest,
) -> None:
    profiles = configured_profiles(tmp_path)
    factory = AnalyzeFactory(AnalyzeConnection(AnalyzeCursor(ANALYZE_COLUMNS, ())))

    with pytest.raises(InvalidArgumentError):
        await SchemaMaintenanceService(profiles, factory).execute(command_request)
    assert factory.configs == []
