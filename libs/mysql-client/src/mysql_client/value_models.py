"""Explicit value types shared by MySQL client boundary models."""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from typing import NewType, TypeAlias

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]

DatabaseScalar: TypeAlias = JsonScalar | bytes | Decimal | date | datetime | time
DatabaseValue: TypeAlias = DatabaseScalar | list["DatabaseValue"] | dict[str, "DatabaseValue"]

SqlText = NewType("SqlText", str)
ProfileName = NewType("ProfileName", str)
ByteCount = NewType("ByteCount", int)
RowCount = NewType("RowCount", int)
Milliseconds = NewType("Milliseconds", float)
