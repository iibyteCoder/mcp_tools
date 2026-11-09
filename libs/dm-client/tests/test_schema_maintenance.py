"""Unit tests for ``DBMS_STATS`` table analysis execution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from dm_client.domain.enums import SqlStatementType, WriteOutcome
from dm_client.domain.errors import PermissionDeniedError, QueryError, WriteError
from dm_client.domain.requests import SchemaAnalyzeRequest
from dm_client.domain.results import AnalyzeOptions, AnalyzeStatistics, TargetMetadata
from dm_client.domain.values import SchemaName, TableName
from dm_client.execution.schema_maintenance import run_schema_analyze
from dm_client.ports.driver import DriverColumn
from dm_client.sql.analyze_queries import (
    GATHER_TABLE_STATS_CALL,
    TABLE_STATS_QUERY,
    build_table_stats_query,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from dm_client.domain.values import DatabaseValue

STATISTICS_COLUMNS = ("NUM_ROWS", "LAST_ANALYZED")


@dataclass(frozen=True)
class QueryFixture:
    """Rows and normalized columns returned for one scripted statistics query."""

    rows: tuple[tuple[DatabaseValue, ...], ...]


def statistics_columns() -> tuple[DriverColumn, ...]:
    return tuple(DriverColumn(name=name, type_name="NUMBER") for name in STATISTICS_COLUMNS)


def empty_statistics() -> QueryFixture:
    return QueryFixture(rows=())


def statistics_fixture(num_rows: DatabaseValue, last_analyzed: DatabaseValue) -> QueryFixture:
    return QueryFixture(rows=((num_rows, last_analyzed),))


class FakeCursor:
    def __init__(self, connection: FakeConnection) -> None:
        self._connection = connection
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
        self._connection.executed.append((sql, tuple(parameters)))
        if "CALL DBMS_STATS" in sql:
            if self._connection.call_error is not None:
                raise self._connection.call_error
            self._description = None
            self._rows = []
            return
        fixture = self._connection.next_statistics()
        self._description = statistics_columns()
        self._rows = list(fixture.rows)

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
        statistics: tuple[QueryFixture, ...] = (),
        *,
        fail_commit: bool = False,
        call_error: BaseException | None = None,
    ) -> None:
        self._statistics = list(statistics)
        self.executed: list[tuple[str, tuple[object, ...]]] = []
        self.fail_commit = fail_commit
        self.call_error = call_error
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def next_statistics(self) -> QueryFixture:
        if not self._statistics:
            raise AssertionError("unexpected statistics query")
        return self._statistics.pop(0)

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    def explain(self, sql: str) -> str:
        return f"plan for {sql}"

    def commit(self) -> None:
        if self.fail_commit:
            raise QueryError("commit failed")
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closed = True


def test_run_schema_analyze_reports_before_after_and_commits() -> None:
    analyzed_at = datetime(2026, 11, 8, 18, 30)
    connection = FakeConnection(
        (empty_statistics(), statistics_fixture(77_141, analyzed_at)),
    )

    result = run_schema_analyze(connection, SchemaAnalyzeRequest(table=TableName(value="T")), "dev")

    assert result.schema == "APP"
    assert result.table == "T"
    assert result.partition is None
    assert result.options == AnalyzeOptions(estimate_percent=None, cascade=True, degree=None)
    assert result.before == AnalyzeStatistics()
    assert result.after == AnalyzeStatistics(last_analyzed=analyzed_at, num_rows=77_141)
    assert result.outcome is WriteOutcome.COMMITTED
    assert result.metadata.statement_type is SqlStatementType.CALL
    assert result.metadata.target == TargetMetadata(
        label="dev",
        schema="APP",
        server_version="8.1.4.80",
    )
    assert result.duration_ms >= 0.0

    assert connection.commits == 1
    assert [sql for sql, _ in connection.executed] == [
        TABLE_STATS_QUERY,
        GATHER_TABLE_STATS_CALL,
        TABLE_STATS_QUERY,
    ]
    assert connection.executed[0][1] == ("APP", "T")
    assert connection.executed[1][1] == ("APP", "T", None, None, False, None, None, None, True)
    assert connection.executed[2][1] == ("APP", "T")


def test_run_schema_analyze_binds_partition_options_and_explicit_schema() -> None:
    connection = FakeConnection(
        (empty_statistics(), statistics_fixture(5, datetime(2026, 11, 8, 18, 30))),
    )
    request = SchemaAnalyzeRequest(
        table=TableName(value="T"),
        schema=SchemaName(value="OTHER"),
        partition="P1",
        estimate_percent=10.0,
        cascade=False,
        degree=4,
    )

    result = run_schema_analyze(connection, request, "dev")

    assert result.schema == "OTHER"
    assert result.partition == "P1"
    assert result.options == AnalyzeOptions(estimate_percent=10.0, cascade=False, degree=4)
    assert connection.executed[0] == (
        build_table_stats_query(partitioned=True),
        ("OTHER", "T", "P1"),
    )
    assert connection.executed[1] == (
        GATHER_TABLE_STATS_CALL,
        ("OTHER", "T", "P1", 10.0, False, None, 4, None, False),
    )
    assert connection.executed[2] == (
        build_table_stats_query(partitioned=True),
        ("OTHER", "T", "P1"),
    )


def test_run_schema_analyze_reports_missing_statistics_as_none() -> None:
    connection = FakeConnection((empty_statistics(), empty_statistics()))

    result = run_schema_analyze(connection, SchemaAnalyzeRequest(table=TableName(value="T")), "dev")

    assert result.before == AnalyzeStatistics()
    assert result.after == AnalyzeStatistics()
    assert result.before.num_rows is None
    assert result.after.last_analyzed is None


def test_run_schema_analyze_converts_decimal_counts_and_date_analysis_time() -> None:
    connection = FakeConnection(
        (
            statistics_fixture(Decimal("9"), date(2026, 11, 8)),
            statistics_fixture(Decimal("9"), date(2026, 11, 8)),
        ),
    )

    result = run_schema_analyze(connection, SchemaAnalyzeRequest(table=TableName(value="T")), "dev")

    assert result.after.num_rows == 9
    assert isinstance(result.after.num_rows, int)
    assert result.after.last_analyzed == datetime(2026, 11, 8, 0, 0)


def test_run_schema_analyze_reports_an_unknown_outcome_when_commit_fails() -> None:
    connection = FakeConnection(
        (empty_statistics(), statistics_fixture(3, datetime(2026, 11, 8, 18, 30))),
        fail_commit=True,
    )

    with pytest.raises(WriteError) as caught:
        run_schema_analyze(connection, SchemaAnalyzeRequest(table=TableName(value="T")), "dev")

    assert caught.value.write_outcome is WriteOutcome.UNKNOWN
    assert [sql for sql, _ in connection.executed] == [TABLE_STATS_QUERY, GATHER_TABLE_STATS_CALL]


def test_run_schema_analyze_propagates_a_dbms_stats_permission_error() -> None:
    connection = FakeConnection(
        (empty_statistics(),),
        call_error=PermissionDeniedError("no DBMS_STATS privilege"),
    )

    with pytest.raises(PermissionDeniedError, match="no DBMS_STATS privilege"):
        run_schema_analyze(connection, SchemaAnalyzeRequest(table=TableName(value="T")), "dev")

    assert connection.commits == 0
    assert [sql for sql, _ in connection.executed] == [TABLE_STATS_QUERY, GATHER_TABLE_STATS_CALL]


def test_run_schema_analyze_reports_a_determined_failure_for_an_unexpected_call_error() -> None:
    connection = FakeConnection(
        (empty_statistics(),),
        call_error=RuntimeError("syntax error"),
    )

    with pytest.raises(WriteError) as caught:
        run_schema_analyze(connection, SchemaAnalyzeRequest(table=TableName(value="T")), "dev")

    assert caught.value.write_outcome is WriteOutcome.DETERMINED_FAILURE
    assert "syntax error" in str(caught.value)


def test_run_schema_analyze_rejects_a_short_statistics_row() -> None:
    connection = FakeConnection((QueryFixture(rows=((1,),)), empty_statistics()))

    with pytest.raises(QueryError, match="unexpected row shape"):
        run_schema_analyze(connection, SchemaAnalyzeRequest(table=TableName(value="T")), "dev")
