"""Convert dmPython values into the closed database value union at the boundary.

LOB handles are detected by the ``read``/``close`` protocol instead of by
importing concrete ``dmPython`` LOB classes, which keeps this adapter usable
with fakes and avoids coupling value conversion to the driver module.

Unknown objects are converted with ``str(value)`` only as a documented last
resort: a database value that dmPython returns outside the supported set must
still be renderable, but it is no longer a lossless representation.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextlib import suppress
from datetime import date, datetime, time
from decimal import Decimal
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from dm_client.domain.values import DatabaseValue


def adapt_value(value: object) -> DatabaseValue:
    """Normalize one driver value without leaking driver classes to callers."""

    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    if isinstance(value, memoryview):
        return bytes(value)
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (datetime, date, time)):
        return value

    read = getattr(value, "read", None)
    if callable(read):
        try:
            payload: object = read()
        finally:
            _close_quietly(value)
        return adapt_value(payload)

    if isinstance(value, (list, tuple)):
        items = cast("Sequence[object]", value)
        return [adapt_value(item) for item in items]

    if isinstance(value, Mapping):
        mapping = cast("Mapping[object, object]", value)
        adapted: dict[str, DatabaseValue] = {}
        for key, item in mapping.items():
            if not isinstance(key, str):
                return str(value)
            adapted[key] = adapt_value(item)
        return adapted

    return str(value)


def adapt_row(row: Sequence[object]) -> tuple[DatabaseValue, ...]:
    """Normalize every column value in one driver row."""

    return tuple(adapt_value(value) for value in row)


def _close_quietly(value: object) -> None:
    close = getattr(value, "close", None)
    if callable(close):
        with suppress(Exception):
            close()


__all__ = ["adapt_row", "adapt_value"]
