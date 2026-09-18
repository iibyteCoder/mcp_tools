from __future__ import annotations

import asyncio
from contextlib import AbstractAsyncContextManager
from typing import TYPE_CHECKING

import pytest

from mysql_client.cancellation import CancellationToken
from mysql_client.configuration import MySqlConnectionConfig, SecretValue
from mysql_client.driver_adapter import (
    DriverColumn,
    DriverConnection,
    DriverCursor,
    DriverFailure,
)
from mysql_client.enums import DriverFailureKind, InspectionCommand, SqlStatementType, TransactionAction, WriteOutcome
from mysql_client.errors import (
    AuthenticationError,
    ConnectionError,
    InvalidArgumentError,
    QueryCancelledError,
    QueryTimeoutError,
)
from mysql_client.request_models import ReadRequest, SchemaDescribeRequest, SqlInput, WriteRequest
from mysql_client.session import MySqlSession, SessionState
from mysql_client.value_models import TableName

if TYPE_CHECKING:
    from collections.abc import Sequence

    from mysql_client.value_models import DatabaseParameters


class FakeCursorContext(AbstractAsyncContextManager[DriverCursor]):
    def __init__(self, cursor: FakeCursor) -> None:
        self._cursor = cursor

    async def __aenter__(self) -> DriverCursor:
        return self._cursor

    async def __aexit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        return None


class FakeCursor:
    def __init__(
        self,
        rows: Sequence[Sequence[object]],
        *,
        block: asyncio.Event | None = None,
        rowcount: int = 0,
        lastrowid: int | None = None,
    ) -> None:
        self.description: tuple[DriverColumn, ...] = (
            DriverColumn(name="id", type_name="INT", nullable=False),
            DriverColumn(name="name", type_name="VARCHAR"),
        )
        self._rows = tuple(tuple(row) for row in rows)
        self._position = 0
        self._block = block
        self._rowcount = rowcount
        self._lastrowid = lastrowid
        self.executed: list[tuple[str, DatabaseParameters]] = []

    @property
    def rowcount(self) -> int:
        return self._rowcount

    @property
    def lastrowid(self) -> int | None:
        return self._lastrowid

    async def execute(self, sql: str, parameters: DatabaseParameters) -> None:
        self.executed.append((sql, parameters))
        if self._block is not None:
            await self._block.wait()

    async def fetchmany(self, size: int) -> Sequence[Sequence[object]]:
        end = min(self._position + size, len(self._rows))
        batch = self._rows[self._position : end]
        self._position = end
        return batch


class FakeConnection:
    def __init__(self, cursor: FakeCursor, *, thread_id: int = 7) -> None:
        self.cursor_value = cursor
        self.thread_id = thread_id
        self.begin_count = 0
        self.commit_count = 0
        self.rollback_count = 0
        self.close_count = 0

    def cursor(self) -> AbstractAsyncContextManager[DriverCursor]:
        return FakeCursorContext(self.cursor_value)

    async def begin(self) -> None:
        self.begin_count += 1

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        self.rollback_count += 1

    async def close(self) -> None:
        self.close_count += 1


class FakeFactory:
    def __init__(self, connection: FakeConnection | None = None, failure: DriverFailure | None = None) -> None:
        self.connection = connection
        self.failure = failure
        self.kill_count = 0
        self.killed_thread_id: int | None = None

    async def connect(self, config: MySqlConnectionConfig) -> DriverConnection:
        del config
        if self.failure is not None:
            raise self.failure
        if self.connection is None:
            raise AssertionError("connection was not configured")
        return self.connection

    async def kill_query(self, config: MySqlConnectionConfig, thread_id: int) -> bool:
        del config
        self.kill_count += 1
        self.killed_thread_id = thread_id
        return True


def config() -> MySqlConnectionConfig:
    return MySqlConnectionConfig(
        host="127.0.0.1",
        port=3306,
        user="tester",
        password=SecretValue(_value="not-a-loggable-secret"),
        database="example",
        connect_timeout_seconds=0.2,
        read_timeout_seconds=0.2,
    )


@pytest.mark.asyncio
async def test_session_lifecycle_and_bounded_read_preserve_metadata() -> None:
    cursor = FakeCursor(((1, "one"), (2, "two"), (3, "three")))
    connection = FakeConnection(cursor)
    factory = FakeFactory(connection)

    async with MySqlSession(config(), factory) as session:
        assert session.state is SessionState.OPEN
        result = await session.execute_read(ReadRequest(sql=SqlInput.inline("SELECT id, name FROM items"), max_rows=2))
        assert result.columns[0].name == "id"
        assert result.columns[0].ordinal == 0
        assert result.rows[1].values == (2, "two")
        assert result.metadata.row_count == 2
        assert result.metadata.statement_type is SqlStatementType.SELECT
        assert result.truncated is True

    assert connection.close_count == 1
    assert session.state.value == SessionState.CLOSED.value
    assert "not-a-loggable-secret" not in repr(config())


@pytest.mark.asyncio
async def test_write_transaction_decision_commits_or_rolls_back() -> None:
    commit_connection = FakeConnection(FakeCursor((), rowcount=2, lastrowid=19))
    async with MySqlSession(config(), FakeFactory(commit_connection)) as session:
        committed = await session.execute_write(
            WriteRequest(
                sql=SqlInput.inline("INSERT INTO items(name) VALUES (%s)"), statement_type=SqlStatementType.INSERT
            )
        )
    assert committed.affected_rows == 2
    assert committed.generated_values == (19,)
    assert commit_connection.begin_count == 1
    assert commit_connection.commit_count == 1
    assert commit_connection.rollback_count == 0

    rollback_connection = FakeConnection(FakeCursor((), rowcount=1))
    async with MySqlSession(config(), FakeFactory(rollback_connection)) as session:
        rolled_back = await session.execute_write(
            WriteRequest(
                sql=SqlInput.inline("UPDATE items SET name = %s"),
                statement_type=SqlStatementType.UPDATE,
                transaction=TransactionAction.ROLLBACK,
            )
        )
    assert rolled_back.affected_rows == 1
    assert rollback_connection.commit_count == 0
    assert rollback_connection.rollback_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (DriverFailure(DriverFailureKind.AUTHENTICATION), AuthenticationError),
        (DriverFailure(DriverFailureKind.CONNECTION), ConnectionError),
        (DriverFailure(DriverFailureKind.PARAMETER), InvalidArgumentError),
    ],
)
async def test_connection_failures_are_classified(failure: DriverFailure, expected: type[Exception]) -> None:
    session = MySqlSession(config(), FakeFactory(failure=failure))
    with pytest.raises(expected):
        await session.connect()
    assert session.state is SessionState.INVALIDATED


@pytest.mark.asyncio
async def test_timeout_kills_query_and_discards_connection() -> None:
    block = asyncio.Event()
    connection = FakeConnection(FakeCursor((), block=block))
    factory = FakeFactory(connection)
    session = MySqlSession(config(), factory)
    await session.connect()

    with pytest.raises(QueryTimeoutError):
        await session.execute_read(ReadRequest(sql=SqlInput.inline("SELECT SLEEP(10)"), statement_timeout_seconds=0.01))

    assert factory.kill_count == 1
    assert factory.killed_thread_id == 7
    assert connection.close_count == 1
    assert session.state is SessionState.INVALIDATED


@pytest.mark.asyncio
async def test_write_timeout_reports_unknown_outcome_after_cancelled_executor() -> None:
    block = asyncio.Event()
    connection = FakeConnection(FakeCursor((), block=block))
    factory = FakeFactory(connection)
    session = MySqlSession(config(), factory)
    await session.connect()

    with pytest.raises(QueryTimeoutError) as error:
        await session.execute_write(
            WriteRequest(sql=SqlInput.inline("UPDATE items SET name = %s"), statement_timeout_seconds=0.01)
        )

    assert error.value.write_outcome is WriteOutcome.UNKNOWN
    assert session.state is SessionState.INVALIDATED


@pytest.mark.asyncio
async def test_cancellation_kills_query_and_discards_connection() -> None:
    block = asyncio.Event()
    connection = FakeConnection(FakeCursor((), block=block))
    factory = FakeFactory(connection)
    token = CancellationToken()
    session = MySqlSession(config(), factory, cancellation=token)
    await session.connect()
    running = asyncio.create_task(session.execute_read(ReadRequest(sql=SqlInput.inline("SELECT 1"))))
    await asyncio.sleep(0)
    await token.cancel()

    with pytest.raises(QueryCancelledError):
        await running
    assert factory.kill_count == 1
    assert connection.close_count == 1
    assert session.state is SessionState.INVALIDATED


@pytest.mark.asyncio
async def test_write_cancellation_reports_unknown_outcome_after_cancelled_executor() -> None:
    block = asyncio.Event()
    connection = FakeConnection(FakeCursor((), block=block))
    factory = FakeFactory(connection)
    token = CancellationToken()
    session = MySqlSession(config(), factory, cancellation=token)
    await session.connect()
    running = asyncio.create_task(
        session.execute_write(WriteRequest(sql=SqlInput.inline("UPDATE items SET name = %s")))
    )
    await asyncio.sleep(0)
    await token.cancel()

    with pytest.raises(QueryCancelledError) as error:
        await running

    assert error.value.write_outcome is WriteOutcome.UNKNOWN
    assert session.state is SessionState.INVALIDATED


@pytest.mark.asyncio
async def test_inspection_uses_bound_sql_and_closes_the_session() -> None:
    cursor = FakeCursor((("billing", "invoices"),))
    connection = FakeConnection(cursor)

    async with MySqlSession(config(), FakeFactory(connection)) as session:
        result = await session.execute_inspection(
            SchemaDescribeRequest(database=None, table=TableName(value="invoices"))
        )

    assert result.command is InspectionCommand.SCHEMA_DESCRIBE
    assert cursor.executed[0][1] == (None, "invoices")
    assert "invoices" not in cursor.executed[0][0]
    assert "USE " not in cursor.executed[0][0]
    assert connection.close_count == 1
