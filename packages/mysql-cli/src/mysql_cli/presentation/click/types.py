"""Click parameter types shared by the command groups."""

from __future__ import annotations

from pathlib import Path

import click

from mysql_cli.domain.profile import ProfileName
from mysql_client import DatabaseName, TableName, TransactionAction


class _TypedParamType(click.ParamType[object, object]):
    """Convert a Click string directly into a strict domain value."""

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__()


class _ProfileNameType(_TypedParamType):
    def __init__(self) -> None:
        super().__init__("profile-name")

    def convert(self, value: object, param: click.Parameter | None, ctx: click.Context | None) -> ProfileName:
        if isinstance(value, ProfileName):
            return value
        if not isinstance(value, str):
            self.fail("profile name must be text", param, ctx)
        try:
            return ProfileName(value=value)
        except ValueError as exc:
            self.fail("profile name is invalid", param, ctx)
            raise AssertionError("Click ParamType.fail did not raise") from exc


class _DatabaseNameType(_TypedParamType):
    def __init__(self) -> None:
        super().__init__("database-name")

    def convert(self, value: object, param: click.Parameter | None, ctx: click.Context | None) -> DatabaseName:
        if isinstance(value, DatabaseName):
            return value
        if not isinstance(value, str):
            self.fail("database name must be text", param, ctx)
        try:
            return DatabaseName(value=value)
        except ValueError as exc:
            self.fail("database name is invalid", param, ctx)
            raise AssertionError("Click ParamType.fail did not raise") from exc


class _TableNameType(_TypedParamType):
    def __init__(self) -> None:
        super().__init__("table-name")

    def convert(self, value: object, param: click.Parameter | None, ctx: click.Context | None) -> TableName:
        if isinstance(value, TableName):
            return value
        if not isinstance(value, str):
            self.fail("table name must be text", param, ctx)
        try:
            return TableName(value=value)
        except ValueError as exc:
            self.fail("table name is invalid", param, ctx)
            raise AssertionError("Click ParamType.fail did not raise") from exc


PROFILE_NAME = _ProfileNameType()
DATABASE_NAME = _DatabaseNameType()
TABLE_NAME = _TableNameType()
PATH = click.Path(path_type=Path)
SQL_PATH = click.Path(path_type=Path, allow_dash=True)
POSITIVE_INTEGER = click.IntRange(min=1)
NON_NEGATIVE_INTEGER = click.IntRange(min=0)
POSITIVE_FLOAT = click.FloatRange(min=0.0, min_open=True)
TRANSACTION = click.Choice(tuple(action.value for action in TransactionAction), case_sensitive=True)


__all__ = [
    "DATABASE_NAME",
    "NON_NEGATIVE_INTEGER",
    "PATH",
    "POSITIVE_FLOAT",
    "POSITIVE_INTEGER",
    "PROFILE_NAME",
    "SQL_PATH",
    "TABLE_NAME",
    "TRANSACTION",
]
