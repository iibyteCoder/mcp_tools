from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from typing import TYPE_CHECKING

import pytest

from mysql_client.domain.configuration import MySqlConnectionConfig, SecretValue
from mysql_client.domain.enums import SqlStatementType
from mysql_client.domain.errors import QueryExecutionError
from mysql_client.domain.requests import AnalyzeTableRequest
from mysql_client.domain.results import AnalyzeTableRow
from mysql_client.domain.values import DatabaseName, TableName
from mysql_client.execution.session import MySqlSession
from mysql_client.ports.driver import DriverColumn, DriverConnection, DriverCursor
from mysql_client.sql.maintenance import build_analyze_table_sql

if TYPE_CHECKING:
    from collections.abc import Sequence

    from mysql_client.domain.values import DatabaseParameters

ANALYZE_COLUMNS = (
    DriverColumn(name="Table", type_name="VARCHAR"),
    DriverColumn(name="Op", type_name="VARCHAR"),
    DriverColumn(name="Msg_type", type_name="VARCHAR"),
    DriverColumn(name="Msg_text", type_name="VARCHAR"),
)


class CursorContext(AbstractAsyncContextManager[DriverCursor]):
    def __init__(self, cursor: FakeCursor) -> None:
        self._cursor = cursor

    async def __aenter__(self) -> DriverCursor:
        return self._cursor

    async def __aexit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        del exc_type, exc_value, traceback


class FakeCursor:
    rowcount = 1
    lastrowid = None

    def __init__(self, columns: Sequence[DriverColumn], rows: Sequence[Sequence[object]]) -> None:
        self.description = tuple(columns)
        self._rows = tuple(tuple(row) for row in rows)
        self._position = 0
        self.executed: list[tuple[str, DatabaseParameters]] = []

    async def execute(self, sql: str, parameters: DatabaseParameters) -> None:
        self.executed.append((sql, parameters))
        self._position = 0

    async def fetchmany(self, size: int) -> Sequence[Sequence[object]]:
        end = min(self._position + size, len(self._rows))
        rows = self._rows[self._position : end]
        self._position = end
        return rows


class FakeConnection:
    thread_id = 23

    def __init__(self, cursor: FakeCursor) -> None:
        self.cursor_value = cursor
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

    async def rollback(self) -> None:
        self.rollback_count += 1

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


def analyze_request(*, database: str | None = "billing", table: str = "invoices") -> AnalyzeTableRequest:
    return AnalyzeTableRequest(
        database=None if database is None else DatabaseName(value=database),
        table=TableName(value=table),
    )


def test_build_analyze_table_sql_quotes_database_and_table() -> None:
    assert str(build_analyze_table_sql(analyze_request())) == "ANALYZE TABLE `billing`.`invoices`"


def test_build_analyze_table_sql_quotes_unqualified_table() -> None:
    assert str(build_analyze_table_sql(analyze_request(database=None))) == "ANALYZE TABLE `invoices`"


def test_build_analyze_table_sql_escapes_embedded_backticks() -> None:
    request = AnalyzeTableRequest(
        database=DatabaseName(value="bill`ing"),
        table=TableName(value="in`voices"),
    )

    assert str(build_analyze_table_sql(request)) == "ANALYZE TABLE `bill``ing`.`in``voices`"


def test_analyze_request_rejects_non_positive_timeout() -> None:
    with pytest.raises(ValueError, match="超时"):
        AnalyzeTableRequest(table=TableName(value="invoices"), statement_timeout_seconds=0)


@pytest.mark.asyncio
async def test_execute_analyze_reports_typed_rows_without_transaction() -> None:
    cursor = FakeCursor(ANALYZE_COLUMNS, (("billing.invoices", "analyze", "status", "OK"),))
    connection = FakeConnection(cursor)

    async with MySqlSession(connection_config(), FakeFactory(connection), target_label="dev") as session:
        result = await session.execute_analyze(analyze_request())

    assert result.rows == (
        AnalyzeTableRow(
            table_name="billing.invoices",
            operation="analyze",
            message_type="status",
            message="OK",
        ),
    )
    assert result.metadata.statement_type is SqlStatementType.DDL
    assert result.metadata.row_count == 1
    assert result.metadata.target is not None
    assert result.metadata.target.label == "dev"
    assert result.metadata.target.database == "example"
    assert cursor.executed == [("ANALYZE TABLE `billing`.`invoices`", ())]
    assert connection.begin_count == 0
    assert connection.commit_count == 0
    assert connection.rollback_count == 0
    assert connection.close_count == 1


@pytest.mark.asyncio
async def test_execute_analyze_maps_result_columns_case_insensitively() -> None:
    columns = (
        DriverColumn(name="TABLE", type_name="VARCHAR"),
        DriverColumn(name="op", type_name="VARCHAR"),
        DriverColumn(name="MSG_TYPE", type_name="VARCHAR"),
        DriverColumn(name="msg_text", type_name="VARCHAR"),
    )
    cursor = FakeCursor(columns, (("billing.invoices", "analyze", "note", "table is already up to date"),))

    async with MySqlSession(connection_config(), FakeFactory(FakeConnection(cursor))) as session:
        result = await session.execute_analyze(analyze_request(database=None))

    assert result.rows == (
        AnalyzeTableRow(
            table_name="billing.invoices",
            operation="analyze",
            message_type="note",
            message="table is already up to date",
        ),
    )


@pytest.mark.asyncio
async def test_execute_analyze_rejects_unexpected_columns() -> None:
    cursor = FakeCursor((DriverColumn(name="id", type_name="INT"),), ((1,),))

    async with MySqlSession(connection_config(), FakeFactory(FakeConnection(cursor))) as session:
        with pytest.raises(QueryExecutionError, match="ANALYZE TABLE"):
            await session.execute_analyze(analyze_request())
