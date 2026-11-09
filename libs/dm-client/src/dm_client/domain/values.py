"""Explicit value types shared by the Dameng client boundary models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from typing import NewType, TypeAlias

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
DatabaseScalar: TypeAlias = JsonScalar | bytes | Decimal | date | datetime | time
DatabaseValue: TypeAlias = DatabaseScalar | list["DatabaseValue"] | dict[str, "DatabaseValue"]
DatabaseParameters: TypeAlias = tuple[DatabaseValue, ...]

SqlText = NewType("SqlText", str)

MAX_IDENTIFIER_LENGTH = 128


@dataclass(frozen=True, slots=True, kw_only=True)
class SchemaName:
    """A validated DM schema name supplied by the caller."""

    value: str

    def __post_init__(self) -> None:
        _validate_identifier(self.value, "schema name")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True, kw_only=True)
class TableName:
    """A validated DM table or view name supplied by the caller."""

    value: str

    def __post_init__(self) -> None:
        _validate_identifier(self.value, "table name")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True, kw_only=True)
class ObjectName:
    """A validated generic DM object name supplied by the caller."""

    value: str

    def __post_init__(self) -> None:
        _validate_identifier(self.value, "object name")

    def __str__(self) -> str:
        return self.value


def _validate_identifier(value: str, label: str) -> None:
    if not value or not value.strip():
        raise ValueError(f"{label} must not be empty")
    if len(value) > MAX_IDENTIFIER_LENGTH:
        raise ValueError(f"{label} must not exceed {MAX_IDENTIFIER_LENGTH} characters")
    if "\x00" in value:
        raise ValueError(f"{label} must not contain NUL characters")


__all__ = [
    "MAX_IDENTIFIER_LENGTH",
    "DatabaseParameters",
    "DatabaseScalar",
    "DatabaseValue",
    "JsonScalar",
    "JsonValue",
    "ObjectName",
    "SchemaName",
    "SqlText",
    "TableName",
]
