"""Bounded tabular materialization shared by read and inspection execution.

Row sizes are approximations of the JSON payload, not exact byte counts. Each
scalar is measured after the serialization conventions of the result contract:
strings include quote overhead, bytes are measured as Base64, temporal values
as ISO-8601, and containers add bracket, comma and key overhead. The limit is
therefore a stable safety bound rather than a byte-exact transport guarantee.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, time
from decimal import Decimal
from typing import TYPE_CHECKING, Final

from dm_client.domain.configuration import DEFAULT_FETCH_SIZE
from dm_client.domain.results import (
    ColumnDefinition,
    DatabaseRow,
    ExecutionMetadata,
    QueryResult,
    TargetMetadata,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from dm_client.domain.enums import SqlStatementType
    from dm_client.domain.values import DatabaseValue
    from dm_client.ports.driver import DmCursor, DriverColumn

DEFAULT_MAX_ROWS: Final[int] = 10_000
DEFAULT_MAX_BYTES: Final[int] = 1_048_576

_NULL_SIZE: Final[int] = 4
_BOOLEAN_SIZE: Final[int] = 5
_STRING_QUOTE_OVERHEAD: Final[int] = 2
_CONTAINER_OVERHEAD: Final[int] = 2
_ITEM_SEPARATOR_SIZE: Final[int] = 1
_KEY_QUOTE_OVERHEAD: Final[int] = 2
_BASE64_GROUP_SIZE: Final[int] = 3
_BASE64_ENCODED_SIZE: Final[int] = 4


def build_columns(description: Sequence[DriverColumn] | None) -> tuple[ColumnDefinition, ...]:
    """Convert adapter columns into ordinal result columns."""

    if description is None:
        return ()
    return tuple(
        ColumnDefinition(
            name=column.name,
            type_name=column.type_name,
            nullable=column.nullable,
            ordinal=ordinal,
        )
        for ordinal, column in enumerate(description)
    )


def build_query_result(
    cursor: DmCursor,
    metadata: ExecutionMetadata,
    max_rows: int,
    max_bytes: int,
) -> QueryResult:
    """Fetch at most ``max_rows`` rows and ``max_bytes`` approximate payload size."""

    columns = build_columns(cursor.description)
    rows: list[DatabaseRow] = []
    byte_count = 0
    truncated = False

    while True:
        remaining = max_rows - len(rows)
        batch_size = min(DEFAULT_FETCH_SIZE, remaining + 1)
        batch = cursor.fetchmany(batch_size)
        if not batch:
            break
        for raw_row in batch:
            if len(rows) >= max_rows:
                truncated = True
                break
            row = DatabaseRow.from_values(raw_row)
            row_size = approximate_row_size(row)
            if byte_count + row_size > max_bytes:
                truncated = True
                break
            rows.append(row)
            byte_count += row_size
        if truncated:
            break
        if len(batch) < batch_size:
            break
        if len(rows) >= max_rows:
            truncated = bool(cursor.fetchmany(1))
            break

    return QueryResult(
        columns=columns,
        rows=tuple(rows),
        metadata=replace(metadata, row_count=len(rows)),
        truncated=truncated,
    )


def approximate_row_size(row: DatabaseRow) -> int:
    """Return the approximate serialized size of one row."""

    return sum(approximate_value_size(value) for value in row.values)


def approximate_value_size(value: DatabaseValue) -> int:
    """Return the approximate serialized size of one database value."""

    if value is None:
        return _NULL_SIZE
    if isinstance(value, bool):
        return _BOOLEAN_SIZE
    if isinstance(value, int):
        return len(str(value))
    if isinstance(value, float):
        return len(repr(value))
    if isinstance(value, str):
        return len(value.encode("utf-8")) + _STRING_QUOTE_OVERHEAD
    if isinstance(value, bytes):
        base64_size = (len(value) + _BASE64_GROUP_SIZE - 1) // _BASE64_GROUP_SIZE * _BASE64_ENCODED_SIZE
        return base64_size + _STRING_QUOTE_OVERHEAD
    if isinstance(value, Decimal):
        return len(str(value))
    if isinstance(value, (datetime, date, time)):
        return len(value.isoformat()) + _STRING_QUOTE_OVERHEAD
    if isinstance(value, list):
        return _CONTAINER_OVERHEAD + sum(approximate_value_size(item) for item in value) + max(
            0, len(value) - 1
        ) * _ITEM_SEPARATOR_SIZE
    if isinstance(value, dict):
        size = _CONTAINER_OVERHEAD
        for index, (key, item) in enumerate(value.items()):
            if index:
                size += _ITEM_SEPARATOR_SIZE
            size += len(key.encode("utf-8")) + _KEY_QUOTE_OVERHEAD
            size += _ITEM_SEPARATOR_SIZE + approximate_value_size(item)
        return size
    return len(str(value).encode("utf-8"))


def build_metadata(
    statement_type: SqlStatementType,
    started_at: datetime,
    target: TargetMetadata | None,
    row_count: int = 0,
    affected_rows: int = 0,
) -> ExecutionMetadata:
    """Build execution metadata measured against ``started_at``."""

    now = datetime.now(tz=started_at.tzinfo) if started_at.tzinfo is not None else datetime.now()
    duration_ms = max((now - started_at).total_seconds() * 1000, 0.0)
    return ExecutionMetadata(
        statement_type=statement_type,
        duration_ms=duration_ms,
        row_count=row_count,
        affected_rows=affected_rows,
        target=target,
        started_at=started_at,
    )


__all__ = [
    "DEFAULT_MAX_BYTES",
    "DEFAULT_MAX_ROWS",
    "approximate_row_size",
    "approximate_value_size",
    "build_columns",
    "build_metadata",
    "build_query_result",
]
