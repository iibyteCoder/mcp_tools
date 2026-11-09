"""Server inspection Click commands."""

from __future__ import annotations

import click

from dm_cli.domain.command import CommandAction, CommandGroup, CommandRequest
from dm_cli.presentation.click.runtime import execute, selected_profile


@click.group()
def server() -> None:
    """Inspect a Dameng server."""


@server.command("inspect")
@click.pass_context
def server_inspect(ctx: click.Context) -> None:
    """Show server identity and session details."""

    execute(
        ctx,
        CommandRequest(
            group=CommandGroup.SERVER,
            action=CommandAction.INSPECT,
            selected_profile=selected_profile(ctx),
        ),
    )


@server.command("capabilities")
@click.pass_context
def server_capabilities(ctx: click.Context) -> None:
    """Show typed server capability facts."""

    execute(
        ctx,
        CommandRequest(
            group=CommandGroup.SERVER,
            action=CommandAction.CAPABILITIES,
            selected_profile=selected_profile(ctx),
        ),
    )


@server.command("parameters")
@click.option("--filter", "parameters_filter", help="case-insensitive substring of the parameter name")
@click.option("--all", "parameters_include_all", is_flag=True, help="include all server parameters")
@click.pass_context
def server_parameters(
    ctx: click.Context,
    parameters_filter: str | None,
    parameters_include_all: bool,
) -> None:
    """List DM server parameters, redacting sensitive values."""

    execute(
        ctx,
        CommandRequest(
            group=CommandGroup.SERVER,
            action=CommandAction.PARAMETERS,
            selected_profile=selected_profile(ctx),
            parameters_filter=parameters_filter,
            parameters_include_all=parameters_include_all,
        ),
    )


__all__ = ["server"]
