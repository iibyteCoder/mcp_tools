"""Connection inspection commands."""

from __future__ import annotations

from typing import cast

import click

from redis_cli.cli_support import run_action, runtime, start_command
from redis_cli.enums import CommandGroup
from redis_cli.json_types import ConnectionStatusData, JsonOutput
from redis_cli.rendering import emit_success


@click.group()
def connection() -> None:
    """Inspect the resolved connection without changing saved profiles."""


@connection.command("status")
@click.pass_context
def connection_status(ctx: click.Context) -> None:
    """Show resolved non-secret connection settings without connecting."""

    current = start_command(ctx, CommandGroup.CONNECTION, "status")
    resolved = current.profile_service.resolve(current.selected_profile, current.overrides)
    data = ConnectionStatusData(
        source=resolved.source.value,
        host=resolved.config.settings.host,
        port=resolved.config.settings.port,
        username=resolved.config.settings.username,
        database=resolved.config.settings.database,
        connection_timeout=resolved.config.settings.connection_timeout,
        tls=resolved.config.tls,
        password_present=bool(resolved.config.password),
    )
    emit_success(cast("JsonOutput", data), current.success_meta(resolved.profile))


@connection.command("connect")
@click.pass_context
def connection_connect(ctx: click.Context) -> None:
    """Connect, ping, and close; connections do not persist between calls."""

    current = runtime(ctx)
    run_action(ctx, current.application.ping, group=CommandGroup.CONNECTION, action="connect")


__all__ = ["connection"]
