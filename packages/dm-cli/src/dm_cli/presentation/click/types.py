"""Click parameter types shared by the DM command groups."""

from __future__ import annotations

from pathlib import Path

import click

from db_cli_kit.profiles import ProfileName
from dm_client.domain.enums import ObjectType, TransactionAction
from dm_client.domain.values import ObjectName, SchemaName, TableName


class _TypedParamType(click.ParamType):
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
            raise AssertionError("Click ParamType.fail did not raise")
        try:
            return ProfileName(value=value)
        except ValueError as exc:
            self.fail("profile name is invalid", param, ctx)
            raise AssertionError("Click ParamType.fail did not raise") from exc


class _SchemaNameType(_TypedParamType):
    def __init__(self) -> None:
        super().__init__("schema-name")

    def convert(self, value: object, param: click.Parameter | None, ctx: click.Context | None) -> SchemaName:
        if isinstance(value, SchemaName):
            return value
        if not isinstance(value, str):
            self.fail("schema name must be text", param, ctx)
            raise AssertionError("Click ParamType.fail did not raise")
        try:
            return SchemaName(value=value)
        except ValueError as exc:
            self.fail("schema name is invalid", param, ctx)
            raise AssertionError("Click ParamType.fail did not raise") from exc


class _TableNameType(_TypedParamType):
    def __init__(self) -> None:
        super().__init__("table-name")

    def convert(self, value: object, param: click.Parameter | None, ctx: click.Context | None) -> TableName:
        if isinstance(value, TableName):
            return value
        if not isinstance(value, str):
            self.fail("table name must be text", param, ctx)
            raise AssertionError("Click ParamType.fail did not raise")
        try:
            return TableName(value=value)
        except ValueError as exc:
            self.fail("table name is invalid", param, ctx)
            raise AssertionError("Click ParamType.fail did not raise") from exc


class _ObjectNameType(_TypedParamType):
    def __init__(self) -> None:
        super().__init__("object-name")

    def convert(self, value: object, param: click.Parameter | None, ctx: click.Context | None) -> ObjectName:
        if isinstance(value, ObjectName):
            return value
        if not isinstance(value, str):
            self.fail("object name must be text", param, ctx)
            raise AssertionError("Click ParamType.fail did not raise")
        try:
            return ObjectName(value=value)
        except ValueError as exc:
            self.fail("object name is invalid", param, ctx)
            raise AssertionError("Click ParamType.fail did not raise") from exc


PROFILE_NAME = _ProfileNameType()
SCHEMA_NAME = _SchemaNameType()
TABLE_NAME = _TableNameType()
OBJECT_NAME = _ObjectNameType()
PATH = click.Path(path_type=Path)
SQL_PATH = click.Path(path_type=Path, allow_dash=True)
POSITIVE_INTEGER = click.IntRange(min=1)
NON_NEGATIVE_INTEGER = click.IntRange(min=0)
POSITIVE_FLOAT = click.FloatRange(min=0.0, min_open=True)
NON_NEGATIVE_FLOAT = click.FloatRange(min=0.0)
PERCENTAGE = click.FloatRange(min=0.0, min_open=True, max=100.0)
TRANSACTION = click.Choice(tuple(action.value for action in TransactionAction), case_sensitive=True)
OBJECT_TYPE = click.Choice(tuple(object_type.value for object_type in ObjectType), case_sensitive=True)


def object_type(value: str) -> ObjectType:
    """Convert one validated Click choice into a typed object type."""

    return ObjectType(value)


__all__ = [
    "NON_NEGATIVE_FLOAT",
    "NON_NEGATIVE_INTEGER",
    "OBJECT_NAME",
    "OBJECT_TYPE",
    "PATH",
    "PERCENTAGE",
    "POSITIVE_FLOAT",
    "POSITIVE_INTEGER",
    "PROFILE_NAME",
    "SCHEMA_NAME",
    "SQL_PATH",
    "TABLE_NAME",
    "TRANSACTION",
    "object_type",
]
