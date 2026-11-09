"""dmPython cursor adapter exposing only the typed driver cursor port."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from dm_client.adapters.dmpython.errors import translate_driver_error
from dm_client.adapters.dmpython.values import adapt_row
from dm_client.ports.driver import DriverColumn, DriverRow

if TYPE_CHECKING:
    from collections.abc import Sequence

    from dm_client.domain.values import DatabaseParameters


class _RawCursor(Protocol):
    """Minimal structural surface exposed by a dmPython cursor."""

    @property
    def description(self) -> Sequence[object] | None: ...

    @property
    def rowcount(self) -> object: ...

    def execute(self, sql: str, parameters: Sequence[object] | None = None) -> object: ...

    def fetchmany(self, size: int) -> Sequence[Sequence[object]]: ...

    def close(self) -> object: ...


class DmpythonCursor:
    """Normalize dmPython rows and column descriptions at the adapter boundary."""

    def __init__(self, raw_cursor: _RawCursor) -> None:
        self._raw_cursor = raw_cursor
        self._last_sql: str | None = None

    @property
    def description(self) -> Sequence[DriverColumn] | None:
        try:
            raw_description = self._raw_cursor.description
        except Exception as exc:
            raise translate_driver_error(exc, sql=self._last_sql) from exc
        if raw_description is None:
            return None
        return tuple(_column_from_raw(raw) for raw in raw_description)

    @property
    def rowcount(self) -> int:
        try:
            value = self._raw_cursor.rowcount
        except Exception as exc:
            raise translate_driver_error(exc, sql=self._last_sql) from exc
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        return 0

    def execute(self, sql: str, parameters: DatabaseParameters = ()) -> None:
        self._last_sql = sql
        try:
            if parameters:
                self._raw_cursor.execute(sql, parameters)
            else:
                self._raw_cursor.execute(sql)
        except Exception as exc:
            raise translate_driver_error(exc, sql=sql) from exc

    def fetchmany(self, size: int) -> tuple[DriverRow, ...]:
        try:
            raw_rows = self._raw_cursor.fetchmany(size)
        except Exception as exc:
            raise translate_driver_error(exc, sql=self._last_sql) from exc
        return tuple(adapt_row(row) for row in raw_rows)

    def close(self) -> None:
        try:
            self._raw_cursor.close()
        except Exception as exc:
            raise translate_driver_error(exc, sql=self._last_sql) from exc


def _column_from_raw(raw: object) -> DriverColumn:
    if isinstance(raw, (tuple, list)) and raw:
        raw_values = tuple(raw)
        type_code = raw_values[1] if len(raw_values) > 1 else "UNKNOWN"
        null_ok = raw_values[6] if len(raw_values) > 6 else None
        type_name = getattr(type_code, "__name__", str(type_code))
        return DriverColumn(
            name=str(raw_values[0]),
            type_name=str(type_name),
            nullable=True if null_ok is None else bool(null_ok),
        )

    name = getattr(raw, "name", "")
    type_code = getattr(raw, "type_code", "UNKNOWN")
    null_ok = getattr(raw, "null_ok", None)
    type_name = getattr(type_code, "__name__", str(type_code))
    return DriverColumn(
        name=str(name),
        type_name=str(type_name),
        nullable=True if null_ok is None else bool(null_ok),
    )


__all__ = ["DmpythonCursor"]
