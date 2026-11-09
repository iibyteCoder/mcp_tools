"""Pure result-set comparison and comparison execution over one DM connection."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Final, TypeAlias

from dm_client.domain.enums import (
    ComparisonDifferenceKind,
    ComparisonLocation,
    ComparisonSide,
    SqlStatementType,
)
from dm_client.domain.requests import ReadRequest
from dm_client.domain.results import (
    CompareResult,
    CompareSideSummary,
    ComparisonDifference,
    ExecutionMetadata,
    QueryResult,
    TargetMetadata,
)
from dm_client.domain.values import DatabaseValue
from dm_client.execution.read import run_read
from dm_client.sql.parser import DmSqlParser

if TYPE_CHECKING:
    from dm_client.domain.requests import CompareRequest
    from dm_client.ports.driver import DmConnection

DEFAULT_MAX_DIFF_SAMPLES: Final[int] = 20

ComparisonReporter: TypeAlias = Callable[
    [
        ComparisonDifferenceKind,
        ComparisonLocation,
        tuple[DatabaseValue, ...] | None,
        int | None,
    ],
    None,
]


@dataclass(frozen=True, slots=True, kw_only=True)
class _KeyedRow:
    """One keyed row with its key values kept for difference reports."""

    key_values: tuple[DatabaseValue, ...]
    values: tuple[DatabaseValue, ...]


def compare_results(
    left: QueryResult,
    right: QueryResult,
    key_columns: tuple[str, ...],
    max_diff_samples: int,
) -> tuple[bool, tuple[ComparisonDifference, ...]]:
    """Compare result shape and values while limiting diagnostic samples."""

    differences: list[ComparisonDifference] = []
    mismatch = False

    def add(
        kind: ComparisonDifferenceKind,
        location: ComparisonLocation,
        key_values: tuple[DatabaseValue, ...] | None = None,
        row_index: int | None = None,
    ) -> None:
        nonlocal mismatch
        mismatch = True
        if len(differences) < max_diff_samples:
            differences.append(
                ComparisonDifference(
                    kind=kind,
                    location=location,
                    key_values=key_values,
                    row_index=row_index,
                )
            )

    def capped() -> bool:
        return max_diff_samples > 0 and len(differences) >= max_diff_samples

    left_columns = tuple((column.name, column.type_name) for column in left.columns)
    right_columns = tuple((column.name, column.type_name) for column in right.columns)
    if left_columns != right_columns:
        add(ComparisonDifferenceKind.COLUMN_DEFINITION, ComparisonLocation.COLUMNS)
        return not mismatch, tuple(differences)

    if key_columns:
        left_indexes = _key_indexes(left, key_columns, add)
        right_indexes = _key_indexes(right, key_columns, add)
        if left_indexes is None or right_indexes is None:
            return not mismatch, tuple(differences)
        left_rows = _rows_by_key(left, left_indexes, add, ComparisonSide.LEFT)
        right_rows = _rows_by_key(right, right_indexes, add, ComparisonSide.RIGHT)
        if left_rows is None or right_rows is None:
            return not mismatch, tuple(differences)

        for key, keyed_row in left_rows.items():
            if key not in right_rows:
                add(ComparisonDifferenceKind.ROW_VALUE, ComparisonLocation.RIGHT_MISSING_KEY, keyed_row.key_values)
            elif left_rows[key].values != right_rows[key].values:
                add(ComparisonDifferenceKind.ROW_VALUE, ComparisonLocation.ROW, keyed_row.key_values)
            if capped():
                return not mismatch, tuple(differences)
        for key, keyed_row in right_rows.items():
            if key not in left_rows:
                add(ComparisonDifferenceKind.ROW_VALUE, ComparisonLocation.LEFT_MISSING_KEY, keyed_row.key_values)
            if capped():
                return not mismatch, tuple(differences)
        return not mismatch, tuple(differences)

    if len(left.rows) != len(right.rows):
        add(ComparisonDifferenceKind.ROW_COUNT, ComparisonLocation.ROW_COUNT)
    for row_index, (left_row, right_row) in enumerate(zip(left.rows, right.rows, strict=False)):
        if left_row != right_row:
            add(ComparisonDifferenceKind.ROW_VALUE, ComparisonLocation.ROW, None, row_index)
            if capped():
                break
    return not mismatch, tuple(differences)


def run_compare(
    connection: DmConnection,
    request: CompareRequest,
    target_label: str,
    *,
    target: TargetMetadata | None = None,
) -> CompareResult:
    """Execute each comparison side once and return a summary-based outcome."""

    resolved_target = target or TargetMetadata(
        label=target_label,
        schema=connection.current_schema,
        server_version=connection.server_version,
    )
    parser = DmSqlParser()
    started_at = datetime.now(timezone.utc)
    started = time.perf_counter()

    left = run_read(
        connection,
        ReadRequest(
            sql=request.left_sql,
            parameters=request.left_parameters,
            statement_timeout_seconds=request.statement_timeout_seconds,
        ),
        parser.parse(request.left_sql),
        target_label,
        target=resolved_target,
    )
    right = run_read(
        connection,
        ReadRequest(
            sql=request.right_sql,
            parameters=request.right_parameters,
            statement_timeout_seconds=request.statement_timeout_seconds,
        ),
        parser.parse(request.right_sql),
        target_label,
        target=resolved_target,
    )

    max_diff_samples = (
        DEFAULT_MAX_DIFF_SAMPLES
        if request.max_diff_samples is None
        else request.max_diff_samples
    )
    equal, differences = compare_results(left, right, request.key_columns, max_diff_samples)
    metadata = ExecutionMetadata(
        statement_type=SqlStatementType.SELECT,
        duration_ms=(time.perf_counter() - started) * 1000,
        target=resolved_target,
        started_at=started_at,
    )
    return CompareResult(
        equal=equal,
        left=_side_summary(left),
        right=_side_summary(right),
        differences=differences,
        metadata=metadata,
    )


def _side_summary(result: QueryResult) -> CompareSideSummary:
    return CompareSideSummary(
        columns=result.columns,
        row_count=len(result.rows),
        truncated=result.truncated,
    )


def _key_indexes(
    result: QueryResult,
    key_columns: tuple[str, ...],
    add: ComparisonReporter,
) -> tuple[int, ...] | None:
    names = tuple(column.name.casefold() for column in result.columns)
    indexes: list[int] = []
    for name in key_columns:
        folded = name.casefold()
        if folded not in names:
            add(ComparisonDifferenceKind.KEY_COLUMN, ComparisonLocation.COLUMNS, None, None)
            return None
        indexes.append(names.index(folded))
    return tuple(indexes)


def _rows_by_key(
    result: QueryResult,
    indexes: tuple[int, ...],
    add: ComparisonReporter,
    side: ComparisonSide,
) -> dict[str, _KeyedRow] | None:
    rows: dict[str, _KeyedRow] = {}
    duplicate_location = (
        ComparisonLocation.LEFT_DUPLICATE_KEY
        if side is ComparisonSide.LEFT
        else ComparisonLocation.RIGHT_DUPLICATE_KEY
    )
    for row in result.rows:
        key_values = tuple(row.values[index] for index in indexes)
        key = json.dumps(key_values, default=str, sort_keys=True, ensure_ascii=False)
        if key in rows:
            add(ComparisonDifferenceKind.DUPLICATE_KEY, duplicate_location, key_values, None)
            return None
        rows[key] = _KeyedRow(key_values=key_values, values=row.values)
    return rows


__all__ = ["DEFAULT_MAX_DIFF_SAMPLES", "compare_results", "run_compare"]
