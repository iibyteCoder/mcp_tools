"""Profile and directory-binding commands."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import click

from redis_cli.cli_support import (
    NONNEGATIVE_INT,
    PATH,
    PORT,
    POSITIVE_FLOAT,
    PROFILE_NAME,
    profile_data,
    profile_text,
    runtime,
)
from redis_cli.domain import ConnectionOverrides, ProfileName, ProfileSetRequest, ProfileSettingsPatch
from redis_cli.enums import ErrorCode
from redis_cli.json_types import CurrentProfileView, PingData
from redis_cli.rendering import CliError, emit_success
from redis_cli.service import parse_redis_url


@click.group()
def profile() -> None:
    """Manage named profiles and directory bindings."""


@profile.command("list")
@click.pass_context
def profile_list(ctx: click.Context) -> None:
    """List configured profiles."""

    current = runtime(ctx)
    rows = [profile_data(item) for item in current.profile_service.list_profiles()]
    emit_success(profile_text(current.selected_profile), rows)


@profile.command("current")
@click.option("--path", type=PATH)
@click.pass_context
def profile_current(ctx: click.Context, path: Path | None) -> None:
    """Show the profile selected by the nearest directory binding."""

    current = runtime(ctx)
    selection = current.profile_service.current(path)
    if selection is None or selection.profile is None:
        emit_success(None, {"profile": None, "path": str(path or Path.cwd())})
        return
    data = CurrentProfileView(
        **profile_data(selection.profile),
        path=str(selection.binding.path if selection.binding is not None else path or Path.cwd()),
    )
    emit_success(selection.profile.name.value, data)


@profile.command("show")
@click.argument("name", type=PROFILE_NAME)
@click.pass_context
def profile_show(ctx: click.Context, name: ProfileName) -> None:
    """Show one profile without its password."""

    current = runtime(ctx)
    emit_success(name.value, profile_data(current.profile_service.require(name)))


@profile.command("set")
@click.argument("name", type=PROFILE_NAME)
@click.option("--host", type=str)
@click.option("--port", type=PORT)
@click.option("--username", type=str)
@click.option("--db", "database", type=NONNEGATIVE_INT)
@click.option("--connection-timeout", type=POSITIVE_FLOAT)
@click.option("--url", type=str)
@click.option("--password", type=str)
@click.option("--no-password", is_flag=True)
@click.option("--description", type=str)
@click.option("--no-description", is_flag=True)
@click.option("--no-bind", is_flag=True)
@click.pass_context
def profile_set(
    ctx: click.Context,
    name: ProfileName,
    host: str | None,
    port: int | None,
    username: str | None,
    database: int | None,
    connection_timeout: float | None,
    url: str | None,
    password: str | None,
    no_password: bool,
    description: str | None,
    no_description: bool,
    no_bind: bool,
) -> None:
    """Create or update one profile."""

    if password is not None and no_password:
        raise CliError(ErrorCode.INVALID_ARGUMENT, "--password and --no-password cannot be combined")
    if description is not None and no_description:
        raise CliError(ErrorCode.INVALID_ARGUMENT, "--description and --no-description cannot be combined")
    parsed = parse_redis_url(url) if url is not None else None
    settings = ProfileSettingsPatch(
        host=host if host is not None else None if parsed is None else parsed.settings.host,
        port=port if port is not None else None if parsed is None else parsed.settings.port,
        username=username if username is not None else None if parsed is None else parsed.settings.username,
        database=database if database is not None else None if parsed is None else parsed.settings.database,
        connection_timeout=(
            connection_timeout
            if connection_timeout is not None
            else None
            if parsed is None
            else parsed.settings.connection_timeout
        ),
        tls=None if parsed is None else parsed.tls,
    )
    selected_password = password if password is not None else None if parsed is None else parsed.password or None
    current = runtime(ctx)
    record = current.profile_service.set(
        ProfileSetRequest(
            name=name,
            settings=settings,
            description=description,
            clear_description=no_description,
            password=selected_password,
            clear_password=no_password,
            bind=not no_bind,
        )
    )
    emit_success(name.value, profile_data(record))


@profile.command("select")
@click.argument("name", type=PROFILE_NAME)
@click.option("--path", type=PATH)
@click.pass_context
def profile_select(ctx: click.Context, name: ProfileName, path: Path | None) -> None:
    """Bind a profile to a directory."""

    current = runtime(ctx)
    binding = current.profile_service.bind(name, path)
    emit_success(name.value, {"profile": name.value, "path": str(binding.path)})


@profile.command("bind")
@click.argument("name", type=PROFILE_NAME)
@click.option("--path", type=PATH)
@click.pass_context
def profile_bind(ctx: click.Context, name: ProfileName, path: Path | None) -> None:
    """Alias for ``profile select``."""

    current = runtime(ctx)
    binding = current.profile_service.bind(name, path)
    emit_success(name.value, {"profile": name.value, "path": str(binding.path)})


@profile.command("clear")
@click.option("--path", type=PATH)
@click.pass_context
def profile_clear(ctx: click.Context, path: Path | None) -> None:
    """Remove the direct binding for a directory."""

    current = runtime(ctx)
    binding = current.profile_service.clear(path)
    emit_success(None, {"cleared": binding is not None, "path": str(path or Path.cwd())})


@profile.command("rename")
@click.argument("old", type=PROFILE_NAME)
@click.argument("new", type=PROFILE_NAME)
@click.pass_context
def profile_rename(ctx: click.Context, old: ProfileName, new: ProfileName) -> None:
    """Rename a profile and preserve its bindings and password."""

    current = runtime(ctx)
    record = current.profile_service.rename(old, new)
    emit_success(new.value, profile_data(record))


@profile.command("remove")
@click.argument("name", type=PROFILE_NAME)
@click.pass_context
def profile_remove(ctx: click.Context, name: ProfileName) -> None:
    """Remove a profile, its password, and all bindings."""

    current = runtime(ctx)
    bindings = current.profile_service.remove(name)
    emit_success(name.value, {"removed": True, "bindings_removed": bindings})


@profile.command("validate")
@click.argument("name", type=PROFILE_NAME)
@click.pass_context
def profile_validate(ctx: click.Context, name: ProfileName) -> None:
    """Validate one profile by issuing PING."""

    current = runtime(ctx)
    result = current.application.ping(name, ConnectionOverrides())
    pong = cast("PingData", result.data)["pong"]
    emit_success(name.value, {"validated": True, "pong": pong})


__all__ = ["profile"]
