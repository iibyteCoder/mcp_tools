"""Unit tests for pure result comparison and comparison execution."""

from __future__ import annotations

from typing import TYPE_CHECKING

from dm_client.domain.enums import (
    ComparisonDifferenceKind,
    ComparisonLocation,
    SqlStatementType,
)
from dm_client.domain.requests import CompareRequest, SqlInput
from dm_client.domain.results import (
    ColumnDefinition,
    CompareResult,
    DatabaseRow,
    ExecutionMetadata,
    QueryResult,
    TargetMetadata,
)
from dm_client.execution import compare as compare_module
from dm_client.execution.compare import DEFAULT_MAX_DIFF_SAMPLES, compare_results, run_compare

if TYPE_CHECKING:
    from dm_client.domain.requests import ParsedSql, ReadRequest
    from dm_client.ports.driver import DmConnection

TARGET = TargetMetadata(
    label="test",
    host="127.0.0.1",
    port=15237,
    schema="APP",
    server_version="8.1.4.80",
)


def result_from(
    columns: tuple[tuple[str, str], ...],
    rows: tuple[tuple[object, ...], ...],
    *,
    truncated: bool = False,
) -> QueryResult:
    return QueryResult(
        columns=tuple(
            ColumnDefinition(name=name, type_name=type_name, ordinal=index)
            for index, (name, type_name) in enumerate(columns)
        ),
        rows=tuple(DatabaseRow.from_values(row) for row in rows),
        metadata=ExecutionMetadata(
            statement_type=SqlStatementType.SELECT,
            duration_ms=0.0,
        ),
        truncated=truncated,
    )


def test_equal_results_have_no_differences() -> None:
    left = result_from((("ID", "INT"),), ((1,), (2,)))
    right = result_from((("ID", "INT"),), ((1,), (2,)))

    equal, differences = compare_results(left, right, (), DEFAULT_MAX_DIFF_SAMPLES)

    assert equal is True
    assert differences == ()


def test_different_column_definitions_are_reported_once() -> None:
    left = result_from((("ID", "INT"),), ((1,),))
    right = result_from((("ID", "VARCHAR"),), ((1,),))

    equal, differences = compare_results(left, right, (), DEFAULT_MAX_DIFF_SAMPLES)

    assert equal is False
    assert len(differences) == 1
    assert differences[0].kind is ComparisonDifferenceKind.COLUMN_DEFINITION
    assert differences[0].location is ComparisonLocation.COLUMNS


def test_row_count_mismatch_is_reported() -> None:
    left = result_from((("ID", "INT"),), ((1,), (2,)))
    right = result_from((("ID", "INT"),), ((1,),))

    equal, differences = compare_results(left, right, (), DEFAULT_MAX_DIFF_SAMPLES)

    assert equal is False
    assert [difference.kind for difference in differences] == [ComparisonDifferenceKind.ROW_COUNT]
    assert differences[0].location is ComparisonLocation.ROW_COUNT


def test_row_value_mismatch_reports_the_row_index() -> None:
    left = result_from((("ID", "INT"),), ((1,), (2,)))
    right = result_from((("ID", "INT"),), ((1,), (3,)))

    equal, differences = compare_results(left, right, (), DEFAULT_MAX_DIFF_SAMPLES)

    assert equal is False
    assert differences[0].kind is ComparisonDifferenceKind.ROW_VALUE
    assert differences[0].location is ComparisonLocation.ROW
    assert differences[0].row_index == 1
    assert differences[0].key_values is None


def test_key_columns_match_case_insensitively_and_ignore_row_order() -> None:
    left = result_from((("ID", "INT"), ("V", "VARCHAR")), ((1, "a"), (2, "b")))
    right = result_from((("ID", "INT"), ("V", "VARCHAR")), ((2, "b"), (1, "a")))

    equal, differences = compare_results(left, right, ("id",), DEFAULT_MAX_DIFF_SAMPLES)

    assert equal is True
    assert differences == ()


def test_missing_key_column_is_reported() -> None:
    left = result_from((("ID", "INT"),), ((1,),))
    right = result_from((("ID", "INT"),), ((1,),))

    equal, differences = compare_results(left, right, ("ABSENT",), DEFAULT_MAX_DIFF_SAMPLES)

    assert equal is False
    assert differences[0].kind is ComparisonDifferenceKind.KEY_COLUMN
    assert differences[0].location is ComparisonLocation.COLUMNS


def test_missing_keys_report_the_key_values_and_side() -> None:
    left = result_from((("ID", "INT"),), ((1,), (2,)))
    right = result_from((("ID", "INT"),), ((1,),))

    equal, differences = compare_results(left, right, ("ID",), DEFAULT_MAX_DIFF_SAMPLES)

    assert equal is False
    assert differences[0].kind is ComparisonDifferenceKind.ROW_VALUE
    assert differences[0].location is ComparisonLocation.RIGHT_MISSING_KEY
    assert differences[0].key_values == (2,)


def test_extra_right_keys_report_left_missing_location() -> None:
    left = result_from((("ID", "INT"),), ((1,),))
    right = result_from((("ID", "INT"),), ((1,), (2,)))

    equal, differences = compare_results(left, right, ("ID",), DEFAULT_MAX_DIFF_SAMPLES)

    assert equal is False
    assert differences[0].location is ComparisonLocation.LEFT_MISSING_KEY
    assert differences[0].key_values == (2,)


def test_duplicate_left_key_is_reported_with_key_values() -> None:
    left = result_from((("ID", "INT"),), ((1,), (1,)))
    right = result_from((("ID", "INT"),), ((1,),))

    equal, differences = compare_results(left, right, ("ID",), DEFAULT_MAX_DIFF_SAMPLES)

    assert equal is False
    assert differences[0].kind is ComparisonDifferenceKind.DUPLICATE_KEY
    assert differences[0].location is ComparisonLocation.LEFT_DUPLICATE_KEY
    assert differences[0].key_values == (1,)


def test_duplicate_right_key_is_reported_with_side_location() -> None:
    left = result_from((("ID", "INT"),), ((1,),))
    right = result_from((("ID", "INT"),), ((1,), (1,)))

    equal, differences = compare_results(left, right, ("ID",), DEFAULT_MAX_DIFF_SAMPLES)

    assert equal is False
    assert differences[0].location is ComparisonLocation.RIGHT_DUPLICATE_KEY


def test_keyed_row_mismatch_reports_key_values() -> None:
    left = result_from((("ID", "INT"), ("V", "VARCHAR")), ((1, "a"),))
    right = result_from((("ID", "INT"), ("V", "VARCHAR")), ((1, "b"),))

    equal, differences = compare_results(left, right, ("ID",), DEFAULT_MAX_DIFF_SAMPLES)

    assert equal is False
    assert differences[0].kind is ComparisonDifferenceKind.ROW_VALUE
    assert differences[0].location is ComparisonLocation.ROW
    assert differences[0].key_values == (1,)
    assert differences[0].row_index is None


def test_differences_are_capped_but_equality_is_still_false() -> None:
    left = result_from((("ID", "INT"),), ((1,), (2,), (3,), (4,)))
    right = result_from((("ID", "INT"),), ((10,), (20,), (30,), (40,)))

    equal, differences = compare_results(left, right, (), 2)

    assert equal is False
    assert len(differences) == 2

    equal_zero, zero_differences = compare_results(left, right, (), 0)

    assert equal_zero is False
    assert zero_differences == ()


def test_run_compare_executes_each_side_once_and_summarizes_without_rows() -> None:
    left = result_from((("ID", "INT"),), ((1,), (2,)), truncated=True)
    right = result_from((("ID", "INT"),), ((3,),))
    recorder = ReadRecorder((left, right))
    original = compare_module.run_read
    compare_module.run_read = recorder  # type: ignore[assignment]
    try:
        request = CompareRequest(
            left_sql=SqlInput.inline("SELECT 1 AS ID FROM DUAL"),
            right_sql=SqlInput.inline("SELECT 2 AS ID FROM DUAL"),
            max_diff_samples=1,
        )
        result = run_compare(FakeConnection(), request, "test", target=TARGET)
    finally:
        compare_module.run_read = original  # type: ignore[assignment]

    assert isinstance(result, CompareResult)
    assert result.equal is False
    assert result.left.row_count == 2
    assert result.left.truncated is True
    assert [column.name for column in result.left.columns] == ["ID"]
    assert result.right.row_count == 1
    assert result.right.truncated is False
    assert len(result.differences) == 1
    assert result.metadata is not None
    assert result.metadata.statement_type is SqlStatementType.SELECT
    assert result.metadata.target == TARGET
    assert len(recorder.calls) == 2
    assert recorder.calls[0].sql == request.left_sql
    assert recorder.calls[1].sql == request.right_sql


def test_run_compare_uses_the_default_difference_sample_limit() -> None:
    rows = tuple((value,) for value in range(DEFAULT_MAX_DIFF_SAMPLES + 5))
    other_rows = tuple((value + 100,) for value in range(DEFAULT_MAX_DIFF_SAMPLES + 5))
    recorder = ReadRecorder(
        (
            result_from((("ID", "INT"),), rows),
            result_from((("ID", "INT"),), other_rows),
        )
    )
    original = compare_module.run_read
    compare_module.run_read = recorder  # type: ignore[assignment]
    try:
        request = CompareRequest(
            left_sql=SqlInput.inline("SELECT 1 AS ID FROM DUAL"),
            right_sql=SqlInput.inline("SELECT 2 AS ID FROM DUAL"),
        )
        result = run_compare(FakeConnection(), request, "test", target=TARGET)
    finally:
        compare_module.run_read = original  # type: ignore[assignment]

    assert result.equal is False
    assert len(result.differences) == DEFAULT_MAX_DIFF_SAMPLES


class FakeConnection:
    current_schema = "APP"
    server_version = "8.1.4.80"


class ReadRecorder:
    def __init__(self, results: tuple[QueryResult, ...]) -> None:
        self._results = list(results)
        self.calls: list[ReadRequest] = []

    def __call__(
        self,
        connection: DmConnection,
        request: ReadRequest,
        parsed: ParsedSql,
        target_label: str,
        *,
        target: TargetMetadata | None = None,
    ) -> QueryResult:
        del connection, parsed, target_label, target
        self.calls.append(request)
        return self._results.pop(0)
