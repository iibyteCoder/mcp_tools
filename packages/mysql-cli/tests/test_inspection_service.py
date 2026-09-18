from __future__ import annotations

import json
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from mysql_cli.adapters.profile_store import JsonProfileStore
from mysql_cli.application.inspection import InspectionService
from mysql_cli.application.profile import ProfileService
from mysql_cli.domain.command import CommandAction, CommandGroup, CommandRequest
from mysql_cli.domain.profile import ProfileName, ProfileSetRequest, ProfileSettingsPatch
from mysql_cli.ports.secret_store import SecretStore
from mysql_cli.shared.json_codec import encode_json_document
from mysql_client import (
    DatabaseName,
    DriverColumn,
    DriverConnection,
    DriverCursor,
    MySqlConnectionConfig,
    TableName,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from mysql_client.domain.values import DatabaseParameters


@dataclass
class MemorySecretStore(SecretStore):
    values: dict[ProfileName, str]

    def get(self, name: ProfileName) -> str | None:
        return self.values.get(name)

    def set(self, name: ProfileName, password: str) -> None:
        self.values[name] = password

    def delete(self, name: ProfileName) -> None:
        self.values.pop(name, None)


class InspectionCursor:
    description = (DriverColumn(name="database_name", type_name="VARCHAR"),)
    rowcount = 1
    lastrowid = None

    def __init__(self) -> None:
        self.executed: list[tuple[str, DatabaseParameters]] = []

    async def execute(self, sql: str, parameters: DatabaseParameters) -> None:
        self.executed.append((sql, parameters))

    async def fetchmany(self, size: int) -> Sequence[Sequence[object]]:
        del size
        return (("billing",),)


class InspectionCursorContext(AbstractAsyncContextManager[DriverCursor]):
    def __init__(self, cursor: InspectionCursor) -> None:
        self._cursor = cursor

    async def __aenter__(self) -> DriverCursor:
        return self._cursor

    async def __aexit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        del exc_type, exc_value, traceback


class InspectionConnection:
    thread_id = 11

    def __init__(self, cursor: InspectionCursor) -> None:
        self.cursor_value = cursor
        self.close_count = 0

    def cursor(self) -> AbstractAsyncContextManager[DriverCursor]:
        return InspectionCursorContext(self.cursor_value)

    async def begin(self) -> None:
        raise AssertionError("inspection must not begin a transaction")

    async def commit(self) -> None:
        raise AssertionError("inspection must not commit")

    async def rollback(self) -> None:
        raise AssertionError("inspection must not rollback")

    async def close(self) -> None:
        self.close_count += 1


class InspectionFactory:
    def __init__(self, connection: InspectionConnection) -> None:
        self.connection = connection

    async def connect(self, config: MySqlConnectionConfig) -> DriverConnection:
        del config
        return self.connection


@pytest.mark.asyncio
async def test_inspection_service_returns_deterministic_secret_free_output(tmp_path: Path) -> None:
    path = tmp_path / "profiles.json"
    secret_store = MemorySecretStore({})
    profiles = ProfileService(JsonProfileStore(path), secret_store, working_directory=tmp_path)
    profiles.set(
        ProfileSetRequest(
            name=ProfileName(value="dev"),
            settings=ProfileSettingsPatch(host="db.example", user="alice"),
            password="do-not-output",
        )
    )
    cursor = InspectionCursor()
    connection = InspectionConnection(cursor)
    request = CommandRequest(
        group=CommandGroup.SCHEMA,
        action=CommandAction.TABLES,
        selected_profile=ProfileName(value="dev"),
        schema_database=DatabaseName(value="billing"),
    )

    data = await InspectionService(profiles, InspectionFactory(connection)).execute(request)
    document = encode_json_document(data)
    payload = json.loads(document)

    assert data.command_group is CommandGroup.SCHEMA
    assert data.action is CommandAction.TABLES
    assert data.profile == "dev"
    assert payload["status"] == "completed"
    assert payload["result"]["command"] == "schema_tables"
    assert payload["result"]["query"]["rows"] == [{"values": ["billing"]}]
    assert "do-not-output" not in document
    assert cursor.executed[0][1] == ("billing",)
    assert "billing" not in cursor.executed[0][0]
    assert connection.close_count == 1


def test_command_request_keeps_explicit_schema_target() -> None:
    request = CommandRequest(
        group=CommandGroup.SCHEMA,
        action=CommandAction.DESCRIBE,
        schema_database=DatabaseName(value="billing"),
        schema_table=TableName(value="invoices"),
    )

    assert request.schema_database is not None
    assert request.schema_table is not None
