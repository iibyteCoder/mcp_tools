"""Unit tests for the synchronous read and write feature functions."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from dm_client.domain.enums import TransactionAction, WriteOutcome
from dm_client.domain.errors import PermissionDeniedError, QueryError, WriteError
from dm_client.domain.requests import ReadRequest, SqlInput, WriteRequest
from dm_client.execution.read import run_read
from dm_client.execution.write import run_write
from dm_client.ports.driver import DriverColumn
from dm_client.sql.parser import DmSqlParser

if TYPE_CHECKING:
    from collections.abc import Sequence

    from dm_client.domain.requests import ParsedSql


class FakeCursor:
    def __init__(self, rows: Sequence[Sequence[object]] = ()) -> None:
        self.description = (DriverColumn(name="ID", type_name="NUMBER", nullable=False),)
        self._rows = list(rows)
        self.rowcount = 1
        self.executed: list[tuple[str, tuple[object, ...]]] = []
        self.closed = False
        self.fail_execute = False
        self.execute_error: BaseException | None = None

    def execute(self, sql: str, parameters: tuple[object, ...] = ()) -> None:
        self.executed.append((sql, parameters))
        if self.execute_error is not None:
            raise self.execute_error
        if self.fail_execute:
            raise RuntimeError("syntax error")

    def fetchmany(self, size: int) -> Sequence[Sequence[object]]:
        batch = self._rows[:size]
        self._rows = self._rows[size:]
        return batch

    def close(self) -> None:
        self.closed = True


class FakeConnection:
    server_version = "8.1.4.80"
    current_schema = "APP"

    def __init__(self, cursor: FakeCursor | None = None) -> None:
        self._cursor = cursor or FakeCursor()
        self.commits = 0
        self.rollbacks = 0
        self.fail_commit = False
        self.fail_rollback = False

    def cursor(self) -> FakeCursor:
        return self._cursor

    def commit(self) -> None:
        if self.fail_commit:
            raise QueryError("commit failed")
        self.commits += 1

    def rollback(self) -> None:
        if self.fail_rollback:
            raise QueryError("rollback failed")
        self.rollbacks += 1

    def close(self) -> None:
        return None

    def explain(self, sql: str) -> str:
        del sql
        return "plan"


def parsed(sql: str) -> ParsedSql:
    return DmSqlParser().parse(sql)


def test_run_read_executes_original_sql_forwards_parameters_and_closes_cursor() -> None:
    cursor = FakeCursor(rows=[(1,), (2,)])
    connection = FakeConnection(cursor)
    request = ReadRequest(
        sql=SqlInput.inline("SELECT ID FROM t ORDER BY ID;"),
        parameters=(7,),
        max_rows=5,
    )

    result = run_read(connection, request, parsed(request.sql.text), "test")

    assert cursor.executed == [("SELECT ID FROM t ORDER BY ID;", (7,))]
    assert cursor.closed is True
    assert [row.values for row in result.rows] == [(1,), (2,)]
    assert result.metadata.row_count == 2
    assert result.metadata.target is not None
    assert result.metadata.target.schema == "APP"


def test_run_write_ddl_commits_even_when_rollback_is_requested() -> None:
    cursor = FakeCursor()
    connection = FakeConnection(cursor)
    request = WriteRequest(
        sql=SqlInput.inline("CREATE TABLE t (id INT)"),
        transaction=TransactionAction.ROLLBACK,
    )

    result = run_write(connection, request, parsed(request.sql.text), "test")

    assert connection.commits == 1
    assert connection.rollbacks == 0
    assert result.outcome is WriteOutcome.COMMITTED
    assert result.ddl_auto_commit is True


def test_run_write_dml_rolls_back_when_requested() -> None:
    cursor = FakeCursor()
    connection = FakeConnection(cursor)
    request = WriteRequest(
        sql=SqlInput.inline("INSERT INTO t VALUES (1)"),
        transaction=TransactionAction.ROLLBACK,
    )

    result = run_write(connection, request, parsed(request.sql.text), "test")

    assert connection.rollbacks == 1
    assert connection.commits == 0
    assert result.outcome is WriteOutcome.ROLLED_BACK
    assert result.ddl_auto_commit is False


def test_run_write_execute_failure_reports_determined_failure() -> None:
    cursor = FakeCursor()
    cursor.fail_execute = True
    connection = FakeConnection(cursor)
    request = WriteRequest(sql=SqlInput.inline("INSERT INTO t VALUES (1)"))

    with pytest.raises(WriteError) as caught:
        run_write(connection, request, parsed(request.sql.text), "test")

    assert caught.value.write_outcome is WriteOutcome.DETERMINED_FAILURE
    assert "syntax error" in caught.value.message
    assert cursor.closed is True


def test_run_write_propagates_typed_client_errors_from_execute() -> None:
    cursor = FakeCursor()
    cursor.execute_error = PermissionDeniedError("[CODE:-5504] denied")
    connection = FakeConnection(cursor)
    request = WriteRequest(sql=SqlInput.inline("INSERT INTO t VALUES (1)"))

    with pytest.raises(PermissionDeniedError) as caught:
        run_write(connection, request, parsed(request.sql.text), "test")

    assert not isinstance(caught.value, WriteError)
    assert caught.value.code.value == "permission_denied"
    assert cursor.closed is True


def test_run_write_commit_failure_reports_unknown() -> None:
    connection = FakeConnection()
    connection.fail_commit = True
    request = WriteRequest(sql=SqlInput.inline("INSERT INTO t VALUES (1)"))

    with pytest.raises(WriteError) as caught:
        run_write(connection, request, parsed(request.sql.text), "test")

    assert caught.value.write_outcome is WriteOutcome.UNKNOWN


def test_run_write_rollback_failure_reports_unknown() -> None:
    connection = FakeConnection()
    connection.fail_rollback = True
    request = WriteRequest(
        sql=SqlInput.inline("INSERT INTO t VALUES (1)"),
        transaction=TransactionAction.ROLLBACK,
    )

    with pytest.raises(WriteError) as caught:
        run_write(connection, request, parsed(request.sql.text), "test")

    assert caught.value.write_outcome is WriteOutcome.UNKNOWN
