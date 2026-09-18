"""Pure comparison of two materialized query results."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import TYPE_CHECKING

from mysql_client.domain.enums import ComparisonDifferenceKind, ComparisonLocation, ComparisonSide
from mysql_client.domain.results import ComparisonDifference, QueryResult

if TYPE_CHECKING:
    from mysql_client.domain.values import DatabaseValue

ComparisonReporter = Callable[[ComparisonDifferenceKind, ComparisonLocation], None]


def compare_results(
    left: QueryResult,
    right: QueryResult,
    key_columns: tuple[str, ...],
    max_diff_samples: int,
) -> tuple[bool, tuple[ComparisonDifference, ...]]:
    """Compare result shape and values while limiting diagnostic samples."""

    differences: list[ComparisonDifference] = []
    mismatch = False

    def add(kind: ComparisonDifferenceKind, location: ComparisonLocation) -> None:
        nonlocal mismatch
        mismatch = True
        if len(differences) < max_diff_samples:
            differences.append(ComparisonDifference(kind=kind, location=location))

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
        for key in left_rows:
            if key not in right_rows:
                add(ComparisonDifferenceKind.ROW_VALUE, ComparisonLocation.RIGHT_MISSING_KEY)
            elif left_rows[key] != right_rows[key]:
                add(ComparisonDifferenceKind.ROW_VALUE, ComparisonLocation.ROW)
        for key in right_rows:
            if key not in left_rows:
                add(ComparisonDifferenceKind.ROW_VALUE, ComparisonLocation.LEFT_MISSING_KEY)
        return not mismatch, tuple(differences)

    if len(left.rows) != len(right.rows):
        add(ComparisonDifferenceKind.ROW_COUNT, ComparisonLocation.ROW_COUNT)
    for left_row, right_row in zip(left.rows, right.rows, strict=False):
        if left_row != right_row:
            add(ComparisonDifferenceKind.ROW_VALUE, ComparisonLocation.ROW)
            if len(differences) >= max_diff_samples:
                break
    return not mismatch, tuple(differences)


def _key_indexes(
    result: QueryResult,
    key_columns: tuple[str, ...],
    add: ComparisonReporter,
) -> tuple[int, ...] | None:
    indexes: list[int] = []
    column_names = tuple(column.name for column in result.columns)
    for name in key_columns:
        if name not in column_names:
            add(ComparisonDifferenceKind.KEY_COLUMN, ComparisonLocation.COLUMNS)
            return None
        indexes.append(column_names.index(name))
    return tuple(indexes)


def _rows_by_key(
    result: QueryResult,
    indexes: tuple[int, ...],
    add: ComparisonReporter,
    side: ComparisonSide,
) -> dict[str, tuple[DatabaseValue, ...]] | None:
    rows: dict[str, tuple[DatabaseValue, ...]] = {}
    for row in result.rows:
        key_values = tuple(row.values[index] for index in indexes)
        key = json.dumps(key_values, default=str, sort_keys=True, ensure_ascii=False)
        if key in rows:
            duplicate_location = (
                ComparisonLocation.LEFT_DUPLICATE_KEY
                if side is ComparisonSide.LEFT
                else ComparisonLocation.RIGHT_DUPLICATE_KEY
            )
            add(ComparisonDifferenceKind.DUPLICATE_KEY, duplicate_location)
            return None
        rows[key] = row.values
    return rows


__all__ = ["compare_results"]
