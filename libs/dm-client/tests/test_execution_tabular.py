"""Unit tests for bounded tabular materialization and target metadata."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from dm_client.domain.configuration import DmConnectionConfig, SecretValue
from dm_client.domain.enums import SqlStatementType
from dm_client.domain.results import DatabaseRow, ExecutionMetadata, TargetMetadata
from dm_client.execution.tabular import (
    approximate_row_size,
    approximate_value_size,
    build_columns,
    build_metadata,
    build_query_result,
)
from dm_client.execution.target import build_target
from dm_client.ports.driver import DriverColumn


class FakeCursor:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self.description = (
            DriverColumn(name="ID", type_name="NUMBER", nullable=False),
            DriverColumn(name="NAME", type_name="STRING", nullable=True),
        )
        self._rows = rows
        self.fetch_sizes: list[int] = []

    def execute(self, sql: str, parameters: tuple[object, ...] = ()) -> None:
        del sql, parameters

    def fetchmany(self, size: int) -> list[tuple[object, ...]]:
        self.fetch_sizes.append(size)
        batch = self._rows[:size]
        self._rows = self._rows[size:]
        return batch

    def close(self) -> None:
        return None

    @property
    def rowcount(self) -> int:
        return len(self._rows)


class FakeConnection:
    server_version = "8.1.4.80"
    current_schema = "APP"


def metadata() -> ExecutionMetadata:
    return ExecutionMetadata(statement_type=SqlStatementType.SELECT, duration_ms=1.0)


def config() -> DmConnectionConfig:
    return DmConnectionConfig(
        host="127.0.0.1",
        port=15237,
        user="APP",
        password=SecretValue(_value="secret"),
    )


def test_build_columns_adds_ordinals() -> None:
    columns = build_columns(
        (
            DriverColumn(name="ID", type_name="NUMBER", nullable=False),
            DriverColumn(name="NAME", type_name="STRING"),
        )
    )

    assert columns[0].ordinal == 0
    assert columns[1].ordinal == 1
    assert columns[0].nullable is False


def test_build_columns_handles_missing_description() -> None:
    assert build_columns(None) == ()


def test_query_result_stops_at_max_rows_and_marks_truncation() -> None:
    cursor = FakeCursor([(1, "a"), (2, "b"), (3, "c")])

    result = build_query_result(cursor, metadata(), max_rows=2, max_bytes=1_000)

    assert result.rows == (
        DatabaseRow.from_values((1, "a")),
        DatabaseRow.from_values((2, "b")),
    )
    assert result.truncated is True


def test_query_result_does_not_mark_truncation_when_all_rows_fit() -> None:
    cursor = FakeCursor([(1, "a"), (2, "b"), (3, "c")])

    result = build_query_result(cursor, metadata(), max_rows=5, max_bytes=1_000)

    assert len(result.rows) == 3
    assert result.truncated is False


def test_query_result_stops_before_row_exceeding_max_bytes() -> None:
    cursor = FakeCursor([(1, "abcd"), (2, "efgh")])
    one_row_size = approximate_row_size(DatabaseRow.from_values((1, "abcd")))

    result = build_query_result(cursor, metadata(), max_rows=10, max_bytes=one_row_size)

    assert result.rows == (DatabaseRow.from_values((1, "abcd")),)
    assert result.truncated is True


def test_query_result_empty_batch_is_not_truncated() -> None:
    cursor = FakeCursor([])

    result = build_query_result(cursor, metadata(), max_rows=10, max_bytes=1_000)

    assert result.rows == ()
    assert result.truncated is False


def test_approximate_value_size_covers_scalar_and_collection_forms() -> None:
    assert approximate_value_size(None) == 4
    assert approximate_value_size(True) == 5
    assert approximate_value_size("abcd") == 6
    assert approximate_value_size(b"abc") == 6
    assert approximate_value_size(Decimal("1.5")) == 3
    assert approximate_value_size(["a", None]) == 2 + 3 + 4 + 1
    assert approximate_value_size({"a": 1}) == 2 + 1 + 2 + 1 + 1


def test_build_metadata_measures_duration_and_counts() -> None:
    started_at = datetime.now(timezone.utc) - timedelta(milliseconds=10)
    target = TargetMetadata(label="test", schema="APP")

    result = build_metadata(
        SqlStatementType.SELECT,
        started_at,
        target,
        row_count=2,
        affected_rows=0,
    )

    assert result.statement_type is SqlStatementType.SELECT
    assert result.duration_ms >= 10
    assert result.row_count == 2
    assert result.target == target
    assert result.started_at == started_at


def test_build_target_uses_connection_schema_and_version() -> None:
    target = build_target("test", config(), FakeConnection())

    assert target.label == "test"
    assert target.host == "127.0.0.1"
    assert target.port == 15237
    assert target.schema == "APP"
    assert target.server_version == "8.1.4.80"
