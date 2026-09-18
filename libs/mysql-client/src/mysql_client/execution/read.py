"""Bounded read execution and database-value normalization."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import date, datetime, time
from decimal import Decimal
from typing import TYPE_CHECKING

from mysql_client.domain.results import (
    ColumnDefinition,
    DatabaseRow,
    ExecutionMetadata,
    QueryResult,
    TargetMetadata,
)

if TYPE_CHECKING:
    from mysql_client.domain.requests import ReadRequest
    from mysql_client.domain.values import DatabaseValue
    from mysql_client.ports.driver import DriverColumn, DriverConnection, DriverCursor


def normalize_database_value(value: object) -> DatabaseValue:
    """Normalize values accepted from aiomysql into the domain value union."""

    if value is None or isinstance(value, (str, int, float, bool, bytes, Decimal, datetime, date, time)):
        return value
    if isinstance(value, (list, tuple)):
        return [normalize_database_value(item) for item in value]
    if isinstance(value, Mapping):
        normalized: dict[str, DatabaseValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("数据库映射值的键必须是字符串")
            normalized[key] = normalize_database_value(item)
        return normalized
    raise TypeError(f"不支持的数据库值类型: {value.__class__.__name__}")


def _value_size(value: DatabaseValue) -> int:
    if value is None:
        return 4
    if isinstance(value, bytes):
        return len(value)
    if isinstance(value, str):
        return len(value.encode("utf-8"))
    if isinstance(value, (list, tuple)):
        return sum(_value_size(item) for item in value)
    if isinstance(value, dict):
        return sum(len(key.encode("utf-8")) + _value_size(item) for key, item in value.items())
    try:
        return len(json.dumps(value, default=str, ensure_ascii=False).encode("utf-8"))
    except (TypeError, ValueError):
        return len(str(value).encode("utf-8"))


class ReadExecutor:
    """Execute one read without allowing the driver to materialize an unbounded result."""

    def __init__(self, *, default_max_rows: int, default_max_bytes: int) -> None:
        self._default_max_rows = default_max_rows
        self._default_max_bytes = default_max_bytes

    async def execute(
        self,
        connection: DriverConnection,
        request: ReadRequest,
        *,
        target: TargetMetadata,
        metadata: ExecutionMetadata,
    ) -> QueryResult:
        max_rows = request.max_rows or self._default_max_rows
        max_bytes = request.max_bytes or self._default_max_bytes
        async with connection.cursor() as cursor:
            await cursor.execute(str(request.sql.text), request.parameters)
            columns = self._columns(cursor.description)
            rows, truncated = await self._rows(cursor, max_rows=max_rows, max_bytes=max_bytes)
        result_metadata = ExecutionMetadata(
            statement_type=request.statement_type,
            duration_ms=metadata.duration_ms,
            row_count=len(rows),
            target=target,
            started_at=metadata.started_at,
        )
        return QueryResult(columns=columns, rows=rows, metadata=result_metadata, truncated=truncated)

    async def _rows(
        self, cursor: DriverCursor, *, max_rows: int, max_bytes: int
    ) -> tuple[tuple[DatabaseRow, ...], bool]:
        rows: list[DatabaseRow] = []
        byte_count = 0
        truncated = False
        while len(rows) < max_rows:
            batch_size = min(256, max_rows - len(rows) + 1)
            batch = await cursor.fetchmany(batch_size)
            if not batch:
                break
            for raw_row in batch:
                normalized = DatabaseRow.from_values(normalize_database_value(value) for value in raw_row)
                row_size = sum(_value_size(value) for value in normalized.values)
                if len(rows) >= max_rows or byte_count + row_size > max_bytes:
                    truncated = True
                    break
                rows.append(normalized)
                byte_count += row_size
            if truncated or len(batch) < batch_size:
                break
        return tuple(rows), truncated

    @staticmethod
    def _columns(description: Sequence[DriverColumn] | None) -> tuple[ColumnDefinition, ...]:
        if description is None:
            return ()
        return tuple(
            ColumnDefinition(
                name=column.name,
                type_name=column.type_name,
                nullable=column.nullable,
                ordinal=ordinal,
                default=column.default,
            )
            for ordinal, column in enumerate(description)
        )
