"""Redis server and pipeline commands."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import cast

import click

from redis_cli.cli_support import emit_result, run_action, runtime, start_command
from redis_cli.command_parsing import pipeline_request
from redis_cli.domain.errors import RedisCliError
from redis_cli.enums import CommandGroup, ErrorCode


@click.group()
def server() -> None:
    """Run Redis server operations."""


@server.command("ping")
@click.pass_context
def server_ping(ctx: click.Context) -> None:
    """Check connectivity."""

    current = runtime(ctx)
    run_action(ctx, current.application.ping, group=CommandGroup.SERVER, action="ping")


@server.command("info")
@click.option("--section", default="default", show_default=True)
@click.pass_context
def server_info(ctx: click.Context, section: str) -> None:
    """Return server INFO data."""

    current = start_command(ctx, CommandGroup.SERVER, "info")
    emit_result(current, current.application.info(current.selected_profile, current.overrides, section))


@server.command("dbsize")
@click.pass_context
def server_dbsize(ctx: click.Context) -> None:
    """Return the number of keys in the selected database."""

    current = runtime(ctx)
    run_action(ctx, current.application.dbsize, group=CommandGroup.SERVER, action="dbsize")


@server.command("flushdb")
@click.option("--confirm", is_flag=True, help="explicitly authorize clearing the selected database")
@click.pass_context
def server_flushdb(ctx: click.Context, confirm: bool) -> None:
    """Clear the selected database after explicit confirmation."""

    current = start_command(ctx, CommandGroup.SERVER, "flushdb")
    if not confirm:
        raise RedisCliError(ErrorCode.INVALID_ARGUMENT, "flushdb requires --confirm")
    emit_result(current, current.application.flushdb(current.selected_profile, current.overrides))


@server.command("pipeline")
@click.option("--commands", "commands_text", type=str)
@click.option("--commands-file", type=click.Path(path_type=Path, dir_okay=False))
@click.pass_context
def server_pipeline(ctx: click.Context, commands_text: str | None, commands_file: Path | None) -> None:
    """Execute an ordered JSON array of Redis commands."""

    current = start_command(ctx, CommandGroup.SERVER, "pipeline")
    if (commands_text is None) == (commands_file is None):
        raise RedisCliError(ErrorCode.INVALID_ARGUMENT, "use exactly one of --commands or --commands-file")
    text = commands_text
    if commands_file is not None:
        text = sys.stdin.read() if str(commands_file) == "-" else commands_file.read_text(encoding="utf-8")
    try:
        loaded: object = json.loads(cast("str", text))
    except (TypeError, ValueError) as exc:
        raise RedisCliError(ErrorCode.INVALID_ARGUMENT, "commands must be valid JSON") from exc
    request = pipeline_request(loaded)
    emit_result(current, current.application.pipeline(current.selected_profile, current.overrides, request))


__all__ = ["server"]
