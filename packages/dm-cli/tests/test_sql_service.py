"""Unit tests for the SQL execution service over a fake DM driver."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest

from db_cli_kit.profiles import ProfileName
from dm_cli.adapters.profile_store import JsonProfileStore
from dm_cli.application.input import LoadedInputs, load_inputs
from dm_cli.application.profile import ProfileService
from dm_cli.application.sql import SqlExecutionService
from dm_cli.domain.command import (
    CommandAction,
    CommandGroup,
    CommandRequest,
    CommandStatus,
    SqlInputSpec,
)
from dm_cli.domain.profile import ProfileSetRequest, ProfileSettingsPatch
from dm_cli.ports.secret_store import SecretStore
from dm_client.domain.enums import (
    ComparisonDifferenceKind,
    ComparisonLocation,
    SqlStatementType,
    TransactionAction,
    WriteOutcome,
)
from dm_client.domain.errors import ComparisonError, InvalidArgumentError
from dm_client.domain.requests import SqlInput
from dm_client.domain.results import (
    BenchmarkResult,
    CompareResult,
    ExplainResult,
    QueryResult,
    TargetMetadata,
    WriteResult,
)
from dm_client.ports.driver import DriverColumn

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from dm_cli.application.results import SqlCommandData
    from dm_client.domain.configuration import DmConnectionConfig


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


class FakeCursor:
    def __init__(
        self,
        rows: Sequence[Sequence[object]] = (),
        *,
        responses: dict[str, Sequence[Sequence[object]]] | None = None,
        columns: Sequence[DriverColumn] | None = None,
    ) -> None:
        self.description: Sequence[DriverColumn] = (
            (DriverColumn(name="ID", type_name="NUMBER", nullable=False),)
            if columns is None
            else columns
        )
        self._default_rows = [tuple(row) for row in rows]
        self._responses = {
            sql: [tuple(row) for row in response]
            for sql, response in (responses or {}).items()
        }
        self._rows = list(self._default_rows)
        self.rowcount = 1
        self.executed: list[tuple[str, tuple[object, ...]]] = []
        self.closed = False

    def execute(self, sql: str, parameters: tuple[object, ...] = ()) -> None:
        self.executed.append((sql, parameters))
        self._rows = list(self._responses.get(sql, self._default_rows))

    def fetchmany(self, size: int) -> Sequence[Sequence[object]]:
        batch = self._rows[:size]
        self._rows = self._rows[size:]
        return batch

    def close(self) -> None:
        self.closed = True


class FakeConnection:
    server_version = "8.1.4.80"
    current_schema = "APP"
    str_case_sensitive = False
    max_identifier_length = 128

    def __init__(self, cursor: FakeCursor) -> None:
        self._cursor = cursor
        self.commits = 0
        self.rollbacks = 0
        self.closed = False
        self.plan_text = "1   #NSET2: [1, 1, 1]"
        self.explained: list[str] = []

    def cursor(self) -> FakeCursor:
        return self._cursor

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closed = True

    def explain(self, sql: str) -> str:
        self.explained.append(sql)
        return self.plan_text


class FakeFactory:
    def __init__(self, connection: FakeConnection) -> None:
        self._connection = connection
        self.configs: list[DmConnectionConfig] = []

    def connect(self, config: DmConnectionConfig) -> FakeConnection:
        self.configs.append(config)
        return self._connection


def make_profiles(tmp_path: Path, *, query_timeout: float = 0.0) -> ProfileService:
    profiles = ProfileService(
        JsonProfileStore(tmp_path / "profiles.json", lock_timeout=0.0),
        MemorySecretStore(),
        working_directory=tmp_path,
    )
    profiles.set(
        ProfileSetRequest(
            name=ProfileName(value="dev"),
            settings=ProfileSettingsPatch(
                host="127.0.0.1",
                port=15237,
                user="APP",
                schema="APP",
                query_timeout=query_timeout,
            ),
            password="never-print-this",
        )
    )
    return profiles


def request_for(
    action: CommandAction,
    sql: str,
    *,
    transaction: TransactionAction = TransactionAction.COMMIT,
    timeout_seconds: float | None = None,
    params_file: Path | None = None,
) -> CommandRequest:
    return CommandRequest(
        group=CommandGroup.SQL,
        action=action,
        selected_profile=ProfileName(value="dev"),
        sql_input=SqlInputSpec.inline(sql),
        params_file=params_file,
        sql_timeout_seconds=timeout_seconds,
        sql_transaction=transaction,
    )


def run(
    service: SqlExecutionService,
    request: CommandRequest,
    inputs: LoadedInputs,
) -> SqlCommandData:
    return asyncio.run(service.execute(request, inputs))


def test_read_executes_original_sql_with_positional_parameters(tmp_path: Path) -> None:
    cursor = FakeCursor(rows=[(7,)])
    connection = FakeConnection(cursor)
    factory = FakeFactory(connection)
    params = tmp_path / "params.json"
    params.write_text("[7]", encoding="utf-8")
    request = request_for(CommandAction.READ, "SELECT ID FROM t WHERE ID = ?", params_file=params)
    inputs = load_inputs(request, stdin_text=None)

    data = run(SqlExecutionService(make_profiles(tmp_path), factory), request, inputs)

    assert isinstance(data.result, QueryResult)
    assert cursor.executed == [("SELECT ID FROM t WHERE ID = ?", (7,))]
    assert [row.values for row in data.result.rows] == [(7,)]
    assert data.status is CommandStatus.COMPLETED
    assert data.command_group is CommandGroup.SQL
    assert data.action is CommandAction.READ
    assert data.profile == "dev"
    assert data.result.metadata.target == TargetMetadata(
        label="dev",
        host="127.0.0.1",
        port=15237,
        schema="APP",
        server_version="8.1.4.80",
    )
    assert connection.closed is True


def test_explain_strips_the_prefix_and_never_executes_the_sql(tmp_path: Path) -> None:
    cursor = FakeCursor()
    connection = FakeConnection(cursor)
    factory = FakeFactory(connection)
    request = request_for(CommandAction.EXPLAIN, "EXPLAIN SELECT 1 AS N FROM DUAL")
    inputs = load_inputs(request, stdin_text=None)

    data = run(SqlExecutionService(make_profiles(tmp_path), factory), request, inputs)

    assert isinstance(data.result, ExplainResult)
    assert data.action is CommandAction.EXPLAIN
    assert data.profile == "dev"
    assert connection.explained == ["SELECT 1 AS N FROM DUAL"]
    assert cursor.executed == []
    assert data.result.plan_text == "1   #NSET2: [1, 1, 1]"
    assert [node.operation for node in data.result.nodes] == ["NSET2"]
    assert data.result.metadata.statement_type is SqlStatementType.EXPLAIN
    assert data.result.metadata.target == TargetMetadata(
        label="dev",
        host="127.0.0.1",
        port=15237,
        schema="APP",
        server_version="8.1.4.80",
    )


def test_write_commit_reports_a_committed_outcome(tmp_path: Path) -> None:
    cursor = FakeCursor()
    connection = FakeConnection(cursor)
    factory = FakeFactory(connection)
    request = request_for(CommandAction.WRITE, "INSERT INTO t (ID) VALUES (?)", transaction=TransactionAction.COMMIT)
    inputs = load_inputs(request, stdin_text=None)

    data = run(SqlExecutionService(make_profiles(tmp_path), factory), request, inputs)

    assert isinstance(data.result, WriteResult)
    assert data.result.outcome is WriteOutcome.COMMITTED
    assert data.result.affected_rows == 1
    assert connection.commits == 1
    # The session always rolls back on exit, after the explicit commit.
    assert connection.rollbacks == 1


def test_write_rollback_reports_a_rolled_back_outcome(tmp_path: Path) -> None:
    cursor = FakeCursor()
    connection = FakeConnection(cursor)
    factory = FakeFactory(connection)
    request = request_for(CommandAction.WRITE, "INSERT INTO t (ID) VALUES (?)", transaction=TransactionAction.ROLLBACK)
    inputs = load_inputs(request, stdin_text=None)

    data = run(SqlExecutionService(make_profiles(tmp_path), factory), request, inputs)

    assert isinstance(data.result, WriteResult)
    assert data.result.outcome is WriteOutcome.ROLLED_BACK
    assert connection.commits == 0
    assert connection.rollbacks == 2
    assert cursor.executed == [("INSERT INTO t (ID) VALUES (?)", ())]


def test_profile_query_timeout_reaches_the_driver_config(tmp_path: Path) -> None:
    connection = FakeConnection(FakeCursor())
    factory = FakeFactory(connection)
    request = request_for(CommandAction.READ, "SELECT 1 FROM DUAL")
    inputs = load_inputs(request, stdin_text=None)

    run(SqlExecutionService(make_profiles(tmp_path, query_timeout=7.0), factory), request, inputs)

    assert len(factory.configs) == 1
    assert factory.configs[0].query_timeout_seconds == 7.0
    assert factory.configs[0].schema is not None
    assert factory.configs[0].schema.value == "APP"


def test_request_timeout_overrides_the_profile_timeout(tmp_path: Path) -> None:
    connection = FakeConnection(FakeCursor())
    factory = FakeFactory(connection)
    request = request_for(CommandAction.READ, "SELECT 1 FROM DUAL", timeout_seconds=2.5)
    inputs = load_inputs(request, stdin_text=None)

    run(SqlExecutionService(make_profiles(tmp_path, query_timeout=7.0), factory), request, inputs)

    assert factory.configs[0].query_timeout_seconds == 2.5


def test_missing_sql_input_is_an_invalid_argument(tmp_path: Path) -> None:
    factory = FakeFactory(FakeConnection(FakeCursor()))
    service = SqlExecutionService(make_profiles(tmp_path), factory)
    request = CommandRequest(group=CommandGroup.SQL, action=CommandAction.READ)
    inputs = LoadedInputs(sql=None, parameters=None)

    with pytest.raises(InvalidArgumentError):
        run(service, request, inputs)

    assert factory.configs == []


def test_benchmark_executes_the_original_read_for_each_iteration(tmp_path: Path) -> None:
    sql = "SELECT 1 AS N FROM DUAL"
    cursor = FakeCursor(rows=[(1,)])
    connection = FakeConnection(cursor)
    factory = FakeFactory(connection)
    request = CommandRequest(
        group=CommandGroup.SQL,
        action=CommandAction.BENCHMARK,
        selected_profile=ProfileName(value="dev"),
        sql_input=SqlInputSpec.inline(sql),
        sql_iterations=2,
        sql_warmup_iterations=0,
        sql_timeout_seconds=3.0,
    )
    inputs = load_inputs(request, stdin_text=None)

    data = run(SqlExecutionService(make_profiles(tmp_path), factory), request, inputs)

    assert isinstance(data.result, BenchmarkResult)
    assert data.action is CommandAction.BENCHMARK
    assert data.result.iterations == 2
    assert data.result.warmup_iterations == 0
    assert len(data.result.samples_ms) == 2
    assert data.result.metadata.statement_type is SqlStatementType.SELECT
    assert data.result.metadata.target == TargetMetadata(
        label="dev",
        host="127.0.0.1",
        port=15237,
        schema="APP",
        server_version="8.1.4.80",
    )
    assert cursor.executed == [(sql, ()), (sql, ())]
    assert connection.closed is True


def test_compare_equal_results_return_a_summary(tmp_path: Path) -> None:
    left_sql = "SELECT 1 AS ID FROM DUAL"
    right_sql = "SELECT 1 AS ID FROM DUAL"
    cursor = FakeCursor(responses={left_sql: ((1,),), right_sql: ((1,),)})
    connection = FakeConnection(cursor)
    factory = FakeFactory(connection)
    request = CommandRequest(
        group=CommandGroup.SQL,
        action=CommandAction.COMPARE,
        selected_profile=ProfileName(value="dev"),
        compare_left_sql_input=SqlInputSpec.inline(left_sql),
        compare_right_sql_input=SqlInputSpec.inline(right_sql),
        compare_key_columns=("ID",),
    )
    inputs = load_inputs(request, stdin_text=None)

    data = run(SqlExecutionService(make_profiles(tmp_path), factory), request, inputs)

    assert isinstance(data.result, CompareResult)
    assert data.result.equal is True
    assert data.result.differences == ()
    assert data.result.left.row_count == 1
    assert data.result.right.row_count == 1
    assert [column.name for column in data.result.left.columns] == ["ID"]
    assert data.result.metadata is not None
    assert data.result.metadata.target == TargetMetadata(
        label="dev",
        host="127.0.0.1",
        port=15237,
        schema="APP",
        server_version="8.1.4.80",
    )
    assert cursor.executed == [(left_sql, ()), (right_sql, ())]
    assert connection.closed is True


def test_compare_matches_key_columns_case_insensitively(tmp_path: Path) -> None:
    sql = "SELECT 1 AS ID, 'a' AS V FROM DUAL"
    columns = (
        DriverColumn(name="ID", type_name="NUMBER", nullable=False),
        DriverColumn(name="V", type_name="VARCHAR", nullable=True),
    )
    cursor = FakeCursor(responses={sql: ((1, "a"),)}, columns=columns)
    connection = FakeConnection(cursor)
    factory = FakeFactory(connection)
    request = CommandRequest(
        group=CommandGroup.SQL,
        action=CommandAction.COMPARE,
        selected_profile=ProfileName(value="dev"),
        compare_left_sql_input=SqlInputSpec.inline(sql),
        compare_right_sql_input=SqlInputSpec.inline(sql),
        compare_key_columns=("id",),
    )
    inputs = load_inputs(request, stdin_text=None)

    data = run(SqlExecutionService(make_profiles(tmp_path), factory), request, inputs)

    assert isinstance(data.result, CompareResult)
    assert data.result.equal is True
    assert cursor.executed == [(sql, ()), (sql, ())]


def test_compare_unequal_results_raise_comparison_error_with_differences(tmp_path: Path) -> None:
    left_sql = "SELECT 1 AS ID FROM DUAL"
    right_sql = "SELECT 2 AS ID FROM DUAL"
    cursor = FakeCursor(responses={left_sql: ((1,),), right_sql: ((2,),)})
    connection = FakeConnection(cursor)
    factory = FakeFactory(connection)
    request = CommandRequest(
        group=CommandGroup.SQL,
        action=CommandAction.COMPARE,
        selected_profile=ProfileName(value="dev"),
        compare_left_sql_input=SqlInputSpec.inline(left_sql),
        compare_right_sql_input=SqlInputSpec.inline(right_sql),
    )
    inputs = load_inputs(request, stdin_text=None)

    with pytest.raises(ComparisonError) as caught:
        run(SqlExecutionService(make_profiles(tmp_path), factory), request, inputs)

    assert len(caught.value.differences) == 1
    assert caught.value.differences[0].kind is ComparisonDifferenceKind.ROW_VALUE
    assert caught.value.differences[0].location is ComparisonLocation.ROW
    assert cursor.executed == [(left_sql, ()), (right_sql, ())]
    assert connection.closed is True


def test_compare_binds_left_and_right_parameters_independently(tmp_path: Path) -> None:
    left_sql = "SELECT ID FROM left_t WHERE ID = ?"
    right_sql = "SELECT ID FROM right_t WHERE ID = ?"
    cursor = FakeCursor(responses={left_sql: ((1,),), right_sql: ((2,),)})
    connection = FakeConnection(cursor)
    factory = FakeFactory(connection)
    left_params = tmp_path / "left.json"
    right_params = tmp_path / "right.json"
    left_params.write_text("[1]", encoding="utf-8")
    right_params.write_text("[2]", encoding="utf-8")
    request = CommandRequest(
        group=CommandGroup.SQL,
        action=CommandAction.COMPARE,
        selected_profile=ProfileName(value="dev"),
        compare_left_sql_input=SqlInputSpec.inline(left_sql),
        compare_right_sql_input=SqlInputSpec.inline(right_sql),
        compare_left_params_file=left_params,
        compare_right_params_file=right_params,
        compare_max_diff_samples=5,
    )
    inputs = load_inputs(request, stdin_text=None)

    with pytest.raises(ComparisonError):
        run(SqlExecutionService(make_profiles(tmp_path), factory), request, inputs)

    assert cursor.executed == [(left_sql, (1,)), (right_sql, (2,))]


def test_compare_without_both_sql_inputs_fails_before_connecting(tmp_path: Path) -> None:
    factory = FakeFactory(FakeConnection(FakeCursor()))
    service = SqlExecutionService(make_profiles(tmp_path), factory)
    request = CommandRequest(
        group=CommandGroup.SQL,
        action=CommandAction.COMPARE,
        selected_profile=ProfileName(value="dev"),
    )
    inputs = LoadedInputs(
        sql=None,
        parameters=None,
        compare_left_sql=SqlInput.inline("SELECT 1 AS ID FROM DUAL"),
    )

    with pytest.raises(InvalidArgumentError):
        run(service, request, inputs)

    assert factory.configs == []
