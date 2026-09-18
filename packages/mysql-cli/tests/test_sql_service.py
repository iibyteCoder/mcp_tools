from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from typing import TYPE_CHECKING

import pytest

from mysql_cli.command_model import CommandAction, CommandGroup, CommandRequest, SqlInputSpec
from mysql_cli.input_loader import load_inputs
from mysql_cli.json_codec import encode_json_document
from mysql_cli.profile_models import ProfileName, ProfileSetRequest, ProfileSettingsPatch
from mysql_cli.profile_service import ProfileService
from mysql_cli.profile_store import JsonProfileStore
from mysql_cli.secret_store import SecretStore
from mysql_cli.sql_service import SqlExecutionService
from mysql_client import DriverColumn, DriverConnection, DriverCursor, MySqlConnectionConfig, TransactionAction

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from mysql_client.value_models import DatabaseParameters


class MemorySecretStore(SecretStore):
    def __init__(self) -> None:
        self.values: dict[ProfileName, str] = {}

    def get(self, name: ProfileName) -> str | None:
        return self.values.get(name)

    def set(self, name: ProfileName, password: str) -> None:
        self.values[name] = password

    def delete(self, name: ProfileName) -> None:
        self.values.pop(name, None)


class CursorContext(AbstractAsyncContextManager[DriverCursor]):
    def __init__(self, cursor: SqlCursor) -> None:
        self.cursor = cursor

    async def __aenter__(self) -> DriverCursor:
        return self.cursor

    async def __aexit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        del exc_type, exc_value, traceback


class SqlCursor:
    description = (DriverColumn(name="id", type_name="INT", nullable=False),)
    rowcount = 1
    lastrowid = None

    def __init__(self) -> None:
        self.executed: list[tuple[str, DatabaseParameters]] = []
        self._rows: tuple[tuple[object, ...], ...] = ((1,),)
        self._position = 0

    async def execute(self, sql: str, parameters: DatabaseParameters) -> None:
        self.executed.append((sql, parameters))
        self._position = 0

    async def fetchmany(self, size: int) -> Sequence[Sequence[object]]:
        end = min(self._position + size, len(self._rows))
        rows = self._rows[self._position : end]
        self._position = end
        return rows


class SqlConnection:
    thread_id = 31

    def __init__(self, cursor: SqlCursor) -> None:
        self.cursor_value = cursor
        self.commit_count = 0
        self.rollback_count = 0
        self.close_count = 0

    def cursor(self) -> AbstractAsyncContextManager[DriverCursor]:
        return CursorContext(self.cursor_value)

    async def begin(self) -> None:
        return None

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        self.rollback_count += 1

    async def close(self) -> None:
        self.close_count += 1


class SqlFactory:
    def __init__(self, connection: SqlConnection) -> None:
        self.connection = connection

    async def connect(self, config: MySqlConnectionConfig) -> DriverConnection:
        del config
        return self.connection


def make_profiles(tmp_path: Path) -> ProfileService:
    secrets = MemorySecretStore()
    profiles = ProfileService(JsonProfileStore(tmp_path / "profiles.json"), secrets, working_directory=tmp_path)
    profiles.set(
        ProfileSetRequest(
            name=ProfileName(value="dev"),
            settings=ProfileSettingsPatch(host="db.example", user="alice"),
            password="password-is-not-output",
        )
    )
    return profiles


@pytest.mark.asyncio
async def test_sql_read_service_binds_params_and_emits_typed_json(tmp_path: Path) -> None:
    request = CommandRequest(
        group=CommandGroup.SQL,
        action=CommandAction.READ,
        selected_profile=ProfileName(value="dev"),
        sql_input=SqlInputSpec.inline("SELECT %s"),
        params_file=tmp_path / "params.json",
    )
    (tmp_path / "params.json").write_text('["bound"]', encoding="utf-8")
    inputs = load_inputs(request, stdin_text=None)
    cursor = SqlCursor()
    connection = SqlConnection(cursor)

    data = await SqlExecutionService(make_profiles(tmp_path), SqlFactory(connection)).execute(request, inputs)
    document = encode_json_document(data)

    assert "password-is-not-output" not in document
    assert cursor.executed == [("SELECT %s", ("bound",))]
    assert '"status":"completed"' in document
    assert '"action":"read"' in document
    assert connection.close_count == 1


def test_sql_routes_define_explicit_execution_parameters() -> None:
    write_request = CommandRequest(
        group=CommandGroup.SQL,
        action=CommandAction.WRITE,
        sql_input=SqlInputSpec.inline("UPDATE items SET id = 1"),
        sql_transaction=TransactionAction.ROLLBACK,
        sql_timeout_seconds=2.0,
    )
    benchmark_request = CommandRequest(
        group=CommandGroup.SQL,
        action=CommandAction.BENCHMARK,
        sql_input=SqlInputSpec.inline("SELECT 1"),
        sql_iterations=3,
        sql_warmup_iterations=1,
    )
    compare_request = CommandRequest(
        group=CommandGroup.SQL,
        action=CommandAction.COMPARE,
        compare_left_sql_input=SqlInputSpec.inline("SELECT 1"),
        compare_right_sql_input=SqlInputSpec.inline("SELECT 1"),
        compare_key_columns=("id",),
        compare_max_diff_samples=4,
    )

    assert write_request.sql_transaction.value == "rollback"
    assert write_request.sql_timeout_seconds == 2.0
    assert benchmark_request.sql_iterations == 3
    assert benchmark_request.sql_warmup_iterations == 1
    assert compare_request.compare_key_columns == ("id",)
    assert compare_request.compare_max_diff_samples == 4
