from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from typing import TYPE_CHECKING

import pytest

from mysql_client.configuration import MySqlConnectionConfig, SecretValue
from mysql_client.driver_adapter import DriverColumn, DriverConnection, DriverCursor, DriverFailure
from mysql_client.enums import DriverFailureKind, WriteOutcome
from mysql_client.errors import InvalidArgumentError, WriteExecutionError
from mysql_client.request_models import (
    BenchmarkRequest,
    CompareRequest,
    ExecutionPolicyDefaults,
    ExplainRequest,
    ReadRequest,
    SqlInput,
    WriteRequest,
)
from mysql_client.session import MySqlSession, SessionState

if TYPE_CHECKING:
    from collections.abc import Sequence

    from mysql_client.value_models import DatabaseParameters


class CursorContext(AbstractAsyncContextManager[DriverCursor]):
    def __init__(self, cursor: FakeCursor) -> None:
        self._cursor = cursor

    async def __aenter__(self) -> DriverCursor:
        return self._cursor

    async def __aexit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        del exc_type, exc_value, traceback


class FakeCursor:
    description = (DriverColumn(name="id", type_name="INT", nullable=False),)
    rowcount = 1
    lastrowid = None

    def __init__(
        self,
        rows_by_sql: dict[str, tuple[tuple[object, ...], ...]],
        *,
        execute_failure: DriverFailure | None = None,
    ) -> None:
        self._rows_by_sql = rows_by_sql
        self._rows: tuple[tuple[object, ...], ...] = ()
        self._position = 0
        self._execute_failure = execute_failure
        self.executed: list[tuple[str, DatabaseParameters]] = []

    async def execute(self, sql: str, parameters: DatabaseParameters) -> None:
        self.executed.append((sql, parameters))
        if self._execute_failure is not None:
            raise self._execute_failure
        self._rows = self._rows_by_sql.get(sql, ((1,),))
        self._position = 0

    async def fetchmany(self, size: int) -> Sequence[Sequence[object]]:
        end = min(self._position + size, len(self._rows))
        rows = self._rows[self._position : end]
        self._position = end
        return rows


class FakeConnection:
    thread_id = 17

    def __init__(
        self,
        cursor: FakeCursor,
        *,
        commit_failure: DriverFailure | None = None,
        rollback_failure: DriverFailure | None = None,
    ) -> None:
        self.cursor_value = cursor
        self.commit_failure = commit_failure
        self.rollback_failure = rollback_failure
        self.begin_count = 0
        self.commit_count = 0
        self.rollback_count = 0
        self.close_count = 0

    def cursor(self) -> AbstractAsyncContextManager[DriverCursor]:
        return CursorContext(self.cursor_value)

    async def begin(self) -> None:
        self.begin_count += 1

    async def commit(self) -> None:
        self.commit_count += 1
        if self.commit_failure is not None:
            raise self.commit_failure

    async def rollback(self) -> None:
        self.rollback_count += 1
        if self.rollback_failure is not None:
            raise self.rollback_failure

    async def close(self) -> None:
        self.close_count += 1


class FakeFactory:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    async def connect(self, config: MySqlConnectionConfig) -> DriverConnection:
        del config
        return self.connection


def connection_config() -> MySqlConnectionConfig:
    return MySqlConnectionConfig(
        host="127.0.0.1",
        port=3306,
        user="tester",
        password=SecretValue(_value="secret-for-test-only"),
        database="example",
        connect_timeout_seconds=0.2,
        read_timeout_seconds=0.2,
    )


@pytest.mark.asyncio
async def test_explain_executes_the_user_sql_without_rewriting() -> None:
    sql = "EXPLAIN ANALYZE SELECT id FROM items"
    cursor = FakeCursor({sql: (("plan",),)})
    async with MySqlSession(connection_config(), FakeFactory(FakeConnection(cursor))) as session:
        result = await session.execute_explain(ExplainRequest(sql=SqlInput.inline(sql), analyze=True))

    assert result.rows[0].values == ("plan",)
    assert cursor.executed == [(sql, ())]


@pytest.mark.asyncio
async def test_write_failure_reports_rollback_and_commit_failure_reports_unknown() -> None:
    rollback_cursor = FakeCursor(
        {}, execute_failure=DriverFailure(DriverFailureKind.EXECUTION)
    )
    rollback_connection = FakeConnection(rollback_cursor)
    async with MySqlSession(connection_config(), FakeFactory(rollback_connection)) as session:
        with pytest.raises(WriteExecutionError) as rollback_error:
            await session.execute_write(WriteRequest(sql=SqlInput.inline("UPDATE items SET id = 1")))
        assert rollback_error.value.write_outcome is WriteOutcome.ROLLED_BACK
        assert session.state is SessionState.OPEN

    commit_cursor = FakeCursor({"INSERT INTO items(id) VALUES (1)": ()})
    commit_connection = FakeConnection(
        commit_cursor,
        commit_failure=DriverFailure(DriverFailureKind.EXECUTION),
    )
    session = MySqlSession(connection_config(), FakeFactory(commit_connection))
    await session.connect()
    with pytest.raises(WriteExecutionError) as unknown_error:
        await session.execute_write(WriteRequest(sql=SqlInput.inline("INSERT INTO items(id) VALUES (1)")))
    assert unknown_error.value.write_outcome is WriteOutcome.UNKNOWN
    assert session.state is SessionState.INVALIDATED


@pytest.mark.asyncio
async def test_benchmark_is_bounded_and_executes_only_read_statements() -> None:
    sql = "SELECT id FROM items"
    cursor = FakeCursor({sql: ((1,),)})
    policy = ExecutionPolicyDefaults(
        benchmark_iterations=1,
        benchmark_warmup_iterations=0,
        benchmark_max_iterations=2,
    )
    async with MySqlSession(connection_config(), FakeFactory(FakeConnection(cursor)), policy=policy) as session:
        result = await session.execute_benchmark(BenchmarkRequest(sql=SqlInput.inline(sql), iterations=2))

    assert result.iterations == 2
    assert result.warmup_iterations == 0
    assert len(result.samples_ms) == 2
    assert len(cursor.executed) == 2

    capped_cursor = FakeCursor({sql: ((1,),)})
    capped_session = MySqlSession(
        connection_config(),
        FakeFactory(FakeConnection(capped_cursor)),
        policy=policy,
    )
    async with capped_session:
        with pytest.raises(InvalidArgumentError):
            await capped_session.execute_benchmark(BenchmarkRequest(sql=SqlInput.inline(sql), iterations=3))


@pytest.mark.asyncio
async def test_compare_reports_differences_without_switching_target() -> None:
    left_sql = "SELECT id FROM left_items"
    right_sql = "SELECT id FROM right_items"
    cursor = FakeCursor({left_sql: ((1,),), right_sql: ((2,),)})
    async with MySqlSession(connection_config(), FakeFactory(FakeConnection(cursor))) as session:
        result = await session.execute_compare(
            CompareRequest(
                left_sql=SqlInput.inline(left_sql),
                right_sql=SqlInput.inline(right_sql),
                key_columns=("id",),
                max_diff_samples=0,
            )
        )

    assert result.equal is False
    assert result.differences == ()
    assert [item[0] for item in cursor.executed] == [left_sql, right_sql]


@pytest.mark.asyncio
async def test_parameter_bindings_are_passed_to_the_driver_unchanged() -> None:
    sql = "SELECT %s"
    parameters = ("bound", 7)
    cursor = FakeCursor({sql: ((1,),)})
    async with MySqlSession(connection_config(), FakeFactory(FakeConnection(cursor))) as session:
        await session.execute_read(ReadRequest(sql=SqlInput.inline(sql), parameters=parameters))

    assert cursor.executed == [(sql, parameters)]
