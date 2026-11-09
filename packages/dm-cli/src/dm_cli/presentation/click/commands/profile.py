"""Profile management Click commands."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING

import click

from dm_cli.domain.command import CommandAction, CommandGroup, CommandRequest, DiagnosticErrorType
from dm_cli.domain.profile import ProfileSettingsPatch
from dm_cli.presentation.click.failures import argument_failure
from dm_cli.presentation.click.runtime import execute
from dm_cli.presentation.click.types import (
    NON_NEGATIVE_FLOAT,
    PATH,
    POSITIVE_FLOAT,
    PROFILE_NAME,
    SCHEMA_NAME,
)

if TYPE_CHECKING:
    from pathlib import Path

    from dm_cli.domain.profile import ProfileName
    from dm_client.domain.values import SchemaName


@click.group()
def profile() -> None:
    """Manage named connection profiles and directory bindings."""


@profile.command("list")
@click.pass_context
def profile_list(ctx: click.Context) -> None:
    """List configured profiles."""

    execute(ctx, CommandRequest(group=CommandGroup.PROFILE, action=CommandAction.LIST))


@profile.command("show")
@click.argument("name", type=PROFILE_NAME)
@click.pass_context
def profile_show(ctx: click.Context, name: ProfileName) -> None:
    """Show one profile without its password."""

    execute(ctx, CommandRequest(group=CommandGroup.PROFILE, action=CommandAction.SHOW, profile_name=name))


@profile.command("set")
@click.argument("name", type=PROFILE_NAME)
@click.option("--host", type=str)
@click.option("--port", type=click.IntRange(min=1, max=65_535))
@click.option("--user", type=str)
@click.option("--schema", "schema_name", type=SCHEMA_NAME)
@click.option("--database", "database_name", type=SCHEMA_NAME)
@click.option("--no-schema", is_flag=True)
@click.option("--connect-timeout", type=POSITIVE_FLOAT)
@click.option("--query-timeout", type=NON_NEGATIVE_FLOAT)
@click.option("--description", type=str)
@click.option("--no-description", is_flag=True)
@click.option("--password", type=str)
@click.option("--password-stdin", is_flag=True)
@click.option("--no-password", is_flag=True)
@click.pass_context
def profile_set(
    ctx: click.Context,
    name: ProfileName,
    host: str | None,
    port: int | None,
    user: str | None,
    schema_name: SchemaName | None,
    database_name: SchemaName | None,
    no_schema: bool,
    connect_timeout: float | None,
    query_timeout: float | None,
    description: str | None,
    no_description: bool,
    password: str | None,
    password_stdin: bool,
    no_password: bool,
) -> None:
    """Create or update one profile."""

    selected_schema = _selected_schema(schema_name, database_name, no_schema)
    if no_description and description is not None:
        raise argument_failure(
            "--description and --no-description cannot be used together",
            "--description/--no-description",
        )
    password_selection = _selected_password(password, password_stdin, no_password)
    execute(
        ctx,
        CommandRequest(
            group=CommandGroup.PROFILE,
            action=CommandAction.SET,
            profile_name=name,
            profile_settings=ProfileSettingsPatch(
                host=host,
                port=port,
                user=user,
                schema=None if selected_schema is None else selected_schema.value,
                connect_timeout=connect_timeout,
                query_timeout=query_timeout,
                clear_schema=no_schema,
            ),
            profile_description=description,
            profile_clear_description=no_description,
            profile_password=password_selection.password,
            profile_clear_password=password_selection.clear,
        ),
    )


@profile.command("validate")
@click.argument("name", type=PROFILE_NAME)
@click.pass_context
def profile_validate(ctx: click.Context, name: ProfileName) -> None:
    """Validate one profile by opening a real connection."""

    execute(ctx, CommandRequest(group=CommandGroup.PROFILE, action=CommandAction.VALIDATE, profile_name=name))


@profile.command("bind")
@click.argument("name", type=PROFILE_NAME)
@click.option("--path", type=PATH)
@click.pass_context
def profile_bind(ctx: click.Context, name: ProfileName, path: Path | None) -> None:
    """Bind a profile to a directory."""

    execute(
        ctx,
        CommandRequest(group=CommandGroup.PROFILE, action=CommandAction.BIND, profile_name=name, profile_path=path),
    )


@profile.command("unbind")
@click.option("--path", type=PATH)
@click.pass_context
def profile_unbind(ctx: click.Context, path: Path | None) -> None:
    """Remove the exact directory binding."""

    execute(ctx, CommandRequest(group=CommandGroup.PROFILE, action=CommandAction.UNBIND, profile_path=path))


@profile.command("rename")
@click.argument("old", type=PROFILE_NAME)
@click.argument("new", type=PROFILE_NAME)
@click.pass_context
def profile_rename(ctx: click.Context, old: ProfileName, new: ProfileName) -> None:
    """Rename a profile without overwriting another profile."""

    execute(
        ctx,
        CommandRequest(
            group=CommandGroup.PROFILE,
            action=CommandAction.RENAME,
            profile_name=old,
            profile_new_name=new,
        ),
    )


@profile.command("remove")
@click.argument("name", type=PROFILE_NAME)
@click.pass_context
def profile_remove(ctx: click.Context, name: ProfileName) -> None:
    """Remove a profile and its bindings."""

    execute(ctx, CommandRequest(group=CommandGroup.PROFILE, action=CommandAction.REMOVE, profile_name=name))


@dataclass(frozen=True, slots=True, kw_only=True)
class PasswordSelection:
    """One resolved password option for ``profile set``."""

    password: str | None = None
    clear: bool = False


def _selected_schema(
    schema_name: SchemaName | None,
    database_name: SchemaName | None,
    no_schema: bool,
) -> SchemaName | None:
    if schema_name is not None and database_name is not None:
        raise argument_failure(
            "--schema and --database are aliases and cannot be used together",
            "--schema/--database",
            error_type=DiagnosticErrorType.MUTUALLY_EXCLUSIVE_INPUTS,
        )
    if no_schema and (schema_name is not None or database_name is not None):
        raise argument_failure(
            "--schema/--database and --no-schema cannot be used together",
            "--schema/--database/--no-schema",
            error_type=DiagnosticErrorType.MUTUALLY_EXCLUSIVE_INPUTS,
        )
    return schema_name if schema_name is not None else database_name


def _selected_password(password: str | None, password_stdin: bool, no_password: bool) -> PasswordSelection:
    if password is not None and password_stdin:
        raise argument_failure(
            "--password and --password-stdin cannot be used together",
            "--password/--password-stdin",
            error_type=DiagnosticErrorType.MUTUALLY_EXCLUSIVE_INPUTS,
        )
    if no_password and (password is not None or password_stdin):
        raise argument_failure(
            "--password/--password-stdin and --no-password cannot be used together",
            "--password/--password-stdin/--no-password",
            error_type=DiagnosticErrorType.MUTUALLY_EXCLUSIVE_INPUTS,
        )
    if password_stdin:
        return PasswordSelection(password=_read_stdin_password())
    return PasswordSelection(password=password, clear=no_password)


def _read_stdin_password() -> str:
    text = sys.stdin.read()
    if text.endswith("\n"):
        text = text[:-1]
    if not text:
        raise argument_failure("--password-stdin received an empty password", "--password-stdin")
    return text


__all__ = ["profile"]
