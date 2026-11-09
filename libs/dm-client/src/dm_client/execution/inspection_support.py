"""Shared helpers for read-only server and schema inspection."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from dm_client.domain.configuration import DEFAULT_FETCH_SIZE
from dm_client.domain.enums import SYSTEM_SCHEMAS
from dm_client.domain.results import DatabaseRow, TargetMetadata

if TYPE_CHECKING:
    from dm_client.domain.values import DatabaseValue, SchemaName
    from dm_client.ports.driver import DmConnection, DmCursor, DriverRow


def fetch_all(cursor: DmCursor) -> tuple[DriverRow, ...]:
    """Fetch every remaining driver row in fixed-size batches."""

    rows: list[DriverRow] = []
    while True:
        batch = cursor.fetchmany(DEFAULT_FETCH_SIZE)
        if not batch:
            break
        rows.extend(batch)
    return tuple(rows)


def resolve_target(
    connection: DmConnection,
    target_label: str,
    target: TargetMetadata | None,
) -> TargetMetadata:
    """Return the caller's target or derive one from the live session."""

    return target or TargetMetadata(
        label=target_label,
        schema=connection.current_schema,
        server_version=connection.server_version,
    )


def effective_schema(connection: DmConnection, schema: SchemaName | None) -> str:
    """Return the explicitly requested schema or the session default."""

    return schema.value if schema is not None else connection.current_schema


def database_rows(rows: tuple[DriverRow, ...], *, include_all: bool) -> tuple[DatabaseRow, ...]:
    """Build visible schema rows, hiding system schemas unless requested."""

    system_schemas = frozenset(schema.value for schema in SYSTEM_SCHEMAS)
    visible: list[DatabaseRow] = []
    for row in rows:
        if len(row) < 2 or row[0] is None:
            continue
        name = text_value(row[0])
        is_system = name in system_schemas
        if is_system and not include_all:
            continue
        visible.append(DatabaseRow.from_values((name, row[1], is_system)))
    return tuple(visible)


def timestamp_value(value: DatabaseValue) -> str | None:
    """Render one optional temporal value as ISO-8601 text."""

    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return text_value(value)


def text_value(value: DatabaseValue) -> str:
    """Decode one driver value to display text."""

    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


__all__ = [
    "database_rows",
    "effective_schema",
    "fetch_all",
    "resolve_target",
    "text_value",
    "timestamp_value",
]
