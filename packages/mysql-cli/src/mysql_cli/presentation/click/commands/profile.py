"""Profile management Click commands."""

from __future__ import annotations

from typing import TYPE_CHECKING

import click

from mysql_cli.domain.command import CommandAction, CommandGroup, CommandRequest
from mysql_cli.domain.profile import ProfileSettingsPatch
from mysql_cli.presentation.click.failures import argument_failure
from mysql_cli.presentation.click.runtime import execute
from mysql_cli.presentation.click.types import PATH, POSITIVE_FLOAT, PROFILE_NAME

if TYPE_CHECKING:
    from pathlib import Path

    from mysql_cli.domain.profile import ProfileName


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
@click.option("--database", type=str)
@click.option("--no-database", is_flag=True)
@click.option("--charset", type=str)
@click.option("--connect-timeout", type=POSITIVE_FLOAT)
@click.option("--read-timeout", type=POSITIVE_FLOAT)
@click.option("--description", type=str)
@click.option("--no-description", is_flag=True)
@click.option("--password", type=str)
@click.option("--no-password", is_flag=True)
@click.pass_context
def profile_set(
    ctx: click.Context,
    name: ProfileName,
    host: str | None,
    port: int | None,
    user: str | None,
    database: str | None,
    no_database: bool,
    charset: str | None,
    connect_timeout: float | None,
    read_timeout: float | None,
    description: str | None,
    no_description: bool,
    password: str | None,
    no_password: bool,
) -> None:
    """Create or update one profile."""

    if no_database and database is not None:
        raise argument_failure("--database and --no-database cannot be used together", "--database/--no-database")
    if no_password and password is not None:
        raise argument_failure("--password and --no-password cannot be used together", "--password/--no-password")
    if no_description and description is not None:
        raise argument_failure(
            "--description and --no-description cannot be used together",
            "--description/--no-description",
        )
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
                database=None if no_database else database,
                charset=charset,
                connect_timeout=connect_timeout,
                read_timeout=read_timeout,
                clear_database=no_database,
            ),
            profile_description=description,
            profile_clear_description=no_description,
            profile_password=password,
            profile_clear_password=no_password,
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
        ctx, CommandRequest(group=CommandGroup.PROFILE, action=CommandAction.BIND, profile_name=name, profile_path=path)
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


__all__ = ["profile"]
