"""Profile and directory-binding commands."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, cast

import click

from redis_cli.cli_support import (
    NONNEGATIVE_INT,
    PATH,
    PORT,
    POSITIVE_FLOAT,
    PROFILE_NAME,
    profile_data,
    start_command,
)
from redis_cli.domain.errors import RedisCliError
from redis_cli.domain.profiles import ConnectionOverrides, ProfileSetRequest, ProfileSettingsPatch
from redis_cli.domain.secrets import SecretValue
from redis_cli.enums import CommandGroup, ErrorCode
from redis_cli.json_types import (
    CurrentProfileView,
    JsonOutput,
    PingData,
    ProfileBindingData,
    ProfileClearData,
    ProfileCurrentData,
    ProfileRemoveData,
    ProfileValidateData,
)
from redis_cli.rendering import emit_success
from redis_cli.service import parse_redis_url

if TYPE_CHECKING:
    from db_cli_kit.profiles import ProfileName
    from redis_cli.domain.profiles import ParsedRedisUrl


@click.group()
def profile() -> None:
    """Manage named profiles and directory bindings."""


@profile.command("list")
@click.pass_context
def profile_list(ctx: click.Context) -> None:
    """List configured profiles."""

    current = start_command(ctx, CommandGroup.PROFILE, "list")
    rows = [profile_data(item) for item in current.profile_service.list_profiles()]
    emit_success(cast("JsonOutput", rows), current.success_meta(current.selected_profile))


@profile.command("current")
@click.option("--path", type=PATH)
@click.pass_context
def profile_current(ctx: click.Context, path: Path | None) -> None:
    """Show the profile selected by the nearest directory binding."""

    current = start_command(ctx, CommandGroup.PROFILE, "current")
    selection = current.profile_service.current(path)
    if selection is None or selection.profile is None:
        data = ProfileCurrentData(profile=None, path=str(path or Path.cwd()))
        emit_success(cast("JsonOutput", data), current.success_meta(None))
        return
    view = CurrentProfileView(
        **profile_data(selection.profile),
        path=str(selection.binding.path if selection.binding is not None else path or Path.cwd()),
    )
    emit_success(cast("JsonOutput", view), current.success_meta(selection.profile.name))


@profile.command("show")
@click.argument("name", type=PROFILE_NAME)
@click.pass_context
def profile_show(ctx: click.Context, name: ProfileName) -> None:
    """Show one profile without its password."""

    current = start_command(ctx, CommandGroup.PROFILE, "show", profile=name)
    emit_success(cast("JsonOutput", profile_data(current.profile_service.require(name))), current.success_meta(name))


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
) -> None:
    """Create or update one profile."""

    current = start_command(ctx, CommandGroup.PROFILE, "set", profile=name)
    if password is not None and no_password:
        raise RedisCliError(ErrorCode.INVALID_ARGUMENT, "--password and --no-password cannot be combined")
    if description is not None and no_description:
        raise RedisCliError(ErrorCode.INVALID_ARGUMENT, "--description and --no-description cannot be combined")
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
    record = current.profile_service.set(
        ProfileSetRequest(
            name=name,
            settings=settings,
            description=description,
            clear_description=no_description,
            password=_selected_password(password, parsed),
            clear_password=no_password,
        )
    )
    emit_success(cast("JsonOutput", profile_data(record)), current.success_meta(name))


@profile.command("select")
@click.argument("name", type=PROFILE_NAME)
@click.option("--path", type=PATH)
@click.pass_context
def profile_select(ctx: click.Context, name: ProfileName, path: Path | None) -> None:
    """Bind a profile to a directory."""

    current = start_command(ctx, CommandGroup.PROFILE, "select", profile=name)
    binding = current.profile_service.bind(name, path)
    data = ProfileBindingData(profile=name.value, path=str(binding.path))
    emit_success(cast("JsonOutput", data), current.success_meta(name))


@profile.command("bind")
@click.argument("name", type=PROFILE_NAME)
@click.option("--path", type=PATH)
@click.pass_context
def profile_bind(ctx: click.Context, name: ProfileName, path: Path | None) -> None:
    """Alias for ``profile select``."""

    current = start_command(ctx, CommandGroup.PROFILE, "bind", profile=name)
    binding = current.profile_service.bind(name, path)
    data = ProfileBindingData(profile=name.value, path=str(binding.path))
    emit_success(cast("JsonOutput", data), current.success_meta(name))


@profile.command("clear")
@click.option("--path", type=PATH)
@click.pass_context
def profile_clear(ctx: click.Context, path: Path | None) -> None:
    """Remove the direct binding for a directory."""

    current = start_command(ctx, CommandGroup.PROFILE, "clear")
    binding = current.profile_service.clear(path)
    data = ProfileClearData(cleared=binding is not None, path=str(path or Path.cwd()))
    emit_success(cast("JsonOutput", data), current.success_meta(None))


@profile.command("rename")
@click.argument("old", type=PROFILE_NAME)
@click.argument("new", type=PROFILE_NAME)
@click.pass_context
def profile_rename(ctx: click.Context, old: ProfileName, new: ProfileName) -> None:
    """Rename a profile and preserve its bindings and password."""

    current = start_command(ctx, CommandGroup.PROFILE, "rename", profile=old)
    record = current.profile_service.rename(old, new)
    emit_success(cast("JsonOutput", profile_data(record)), current.success_meta(new))


@profile.command("remove")
@click.argument("name", type=PROFILE_NAME)
@click.pass_context
def profile_remove(ctx: click.Context, name: ProfileName) -> None:
    """Remove a profile, its password, and all bindings."""

    current = start_command(ctx, CommandGroup.PROFILE, "remove", profile=name)
    bindings = current.profile_service.remove(name)
    data = ProfileRemoveData(removed=True, bindings_removed=bindings)
    emit_success(cast("JsonOutput", data), current.success_meta(name))


@profile.command("validate")
@click.argument("name", type=PROFILE_NAME)
@click.pass_context
def profile_validate(ctx: click.Context, name: ProfileName) -> None:
    """Validate one profile by issuing PING."""

    current = start_command(ctx, CommandGroup.PROFILE, "validate", profile=name)
    result = current.application.ping(name, ConnectionOverrides())
    pong = cast("PingData", result.data)["pong"]
    data = ProfileValidateData(validated=True, pong=pong)
    emit_success(cast("JsonOutput", data), current.success_meta(name))


def _selected_password(password: str | None, parsed: ParsedRedisUrl | None) -> SecretValue | None:
    """Choose the explicitly supplied or URL-derived profile password."""

    if password is not None:
        return SecretValue(password)
    if parsed is not None and parsed.password:
        return parsed.password
    return None


__all__ = ["profile"]
