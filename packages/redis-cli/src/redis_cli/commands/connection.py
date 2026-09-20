"""Connection inspection commands."""

from __future__ import annotations

import click

from redis_cli.cli_support import emit_result, profile_text, runtime
from redis_cli.json_types import ConnectionStatusData
from redis_cli.rendering import emit_success


@click.group()
def connection() -> None:
    """Inspect the resolved connection without changing saved profiles."""


@connection.command("status")
@click.pass_context
def connection_status(ctx: click.Context) -> None:
    """Show resolved non-secret connection settings without connecting."""

    current = runtime(ctx)
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
    emit_success(profile_text(resolved.profile), data)


@connection.command("connect")
@click.pass_context
def connection_connect(ctx: click.Context) -> None:
    """Connect, ping, and close; connections do not persist between calls."""

    current = runtime(ctx)
    emit_result(current.application.ping(current.selected_profile, current.overrides))


__all__ = ["connection"]
