"""Explicit value types shared by MySQL client boundary models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from typing import NewType, TypeAlias

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]

DatabaseScalar: TypeAlias = JsonScalar | bytes | Decimal | date | datetime | time
DatabaseValue: TypeAlias = DatabaseScalar | list["DatabaseValue"] | dict[str, "DatabaseValue"]
DatabaseParameters: TypeAlias = tuple[DatabaseValue, ...] | dict[str, DatabaseValue]

SqlText = NewType("SqlText", str)
ProfileName = NewType("ProfileName", str)
ByteCount = NewType("ByteCount", int)
RowCount = NewType("RowCount", int)
Milliseconds = NewType("Milliseconds", float)


MAX_IDENTIFIER_LENGTH = 64


@dataclass(frozen=True, slots=True, kw_only=True)
class DatabaseName:
    """A validated MySQL schema name used as a bound inspection value."""

    value: str

    def __post_init__(self) -> None:
        _validate_identifier(self.value, "数据库名")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True, kw_only=True)
class TableName:
    """A validated MySQL table name used as a bound inspection value."""

    value: str

    def __post_init__(self) -> None:
        _validate_identifier(self.value, "表名")

    def __str__(self) -> str:
        return self.value


def _validate_identifier(value: str, label: str) -> None:
    if not value or not value.strip():
        raise ValueError(f"{label}不能为空")
    if len(value) > MAX_IDENTIFIER_LENGTH:
        raise ValueError(f"{label}长度不能超过 {MAX_IDENTIFIER_LENGTH}")
    if "\x00" in value:
        raise ValueError(f"{label}不能包含 NUL 字符")
