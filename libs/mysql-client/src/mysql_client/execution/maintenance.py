"""Typed mapping for the rows returned by ``ANALYZE TABLE``."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from mysql_client.domain.errors import QueryExecutionError
from mysql_client.domain.results import AnalyzeTableResult, AnalyzeTableRow

if TYPE_CHECKING:
    from mysql_client.domain.results import ColumnDefinition, DatabaseRow, QueryResult
    from mysql_client.domain.values import DatabaseValue

_EXPECTED_COLUMNS: Final[tuple[str, ...]] = ("Table", "Op", "Msg_type", "Msg_text")


@dataclass(frozen=True, slots=True, kw_only=True)
class _AnalyzeColumnIndexes:
    """Column positions required by the typed ``ANALYZE TABLE`` result."""

    table: int
    operation: int
    message_type: int
    message: int


def analyze_table_result(query: QueryResult) -> AnalyzeTableResult:
    """Convert one raw ``ANALYZE TABLE`` query result into typed rows."""

    indexes = _column_indexes(query.columns)
    rows = tuple(_analyze_row(row, indexes) for row in query.rows)
    return AnalyzeTableResult(rows=rows, metadata=query.metadata)


def _column_indexes(columns: tuple[ColumnDefinition, ...]) -> _AnalyzeColumnIndexes:
    positions: dict[str, int] = {}
    for position, column in enumerate(columns):
        positions.setdefault(column.name.casefold(), position)
    missing = tuple(name for name in _EXPECTED_COLUMNS if name.casefold() not in positions)
    if missing:
        raise QueryExecutionError(f"ANALYZE TABLE 返回了意外的列集合; 缺少: {', '.join(missing)}")
    return _AnalyzeColumnIndexes(
        table=positions["table"],
        operation=positions["op"],
        message_type=positions["msg_type"],
        message=positions["msg_text"],
    )


def _analyze_row(row: DatabaseRow, indexes: _AnalyzeColumnIndexes) -> AnalyzeTableRow:
    return AnalyzeTableRow(
        table_name=_text_value(row, indexes.table, "Table"),
        operation=_text_value(row, indexes.operation, "Op"),
        message_type=_text_value(row, indexes.message_type, "Msg_type"),
        message=_text_value(row, indexes.message, "Msg_text"),
    )


def _text_value(row: DatabaseRow, index: int, column_name: str) -> str:
    if index >= len(row.values):
        raise QueryExecutionError(f"ANALYZE TABLE 行缺少 {column_name} 列值")
    value: DatabaseValue = row.values[index]
    if not isinstance(value, str):
        raise QueryExecutionError(f"ANALYZE TABLE 的 {column_name} 列值不是文本")
    return value


__all__ = ["analyze_table_result"]
