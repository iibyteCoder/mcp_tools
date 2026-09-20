"""Click application entry point for the JSON-first Redis CLI."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import click

from redis_cli import __version__
from redis_cli.cli_support import (
    NONNEGATIVE_INT,
    PATH,
    PORT,
    POSITIVE_FLOAT,
    PROFILE_NAME,
    CliRuntime,
    JsonClickGroup,
    create_runtime,
    runtime,
)
from redis_cli.commands import connection, hash, key, list_group, profile, server, set_group, string, zset
from redis_cli.constants import REDIS_CLI_SKILL_PATH
from redis_cli.domain import ConnectionOverrides, ProfileName
from redis_cli.rendering import emit_success

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path


@click.group(
    cls=JsonClickGroup,
    context_settings={"help_option_names": ["-h", "--help"], "max_content_width": 120},
)
@click.version_option(version=__version__, prog_name="db-redis", message="%(prog)s %(version)s")
@click.option("--json", "json_output", is_flag=True, help="emit one JSON document")
@click.option("--profile", "selected_profile", type=PROFILE_NAME, help="select a saved profile")
@click.option("--url", type=str, help="temporary Redis URL override")
@click.option("--host", type=str, help="temporary Redis host override")
@click.option("--port", type=PORT, help="temporary Redis port override")
@click.option("--username", type=str, help="temporary Redis ACL username override")
@click.option("--password", type=str, help="temporary Redis password override")
@click.option("--db", "database", type=NONNEGATIVE_INT, help="temporary logical database override")
@click.option("--connection-timeout", type=POSITIVE_FLOAT, help="temporary connection timeout in seconds")
@click.pass_context
def cli(
    ctx: click.Context,
    json_output: bool,
    selected_profile: ProfileName | None,
    url: str | None,
    host: str | None,
    port: int | None,
    username: str | None,
    password: str | None,
    database: int | None,
    connection_timeout: float | None,
) -> None:
    """JSON-first Redis command line tool."""

    del json_output
    current = runtime(ctx)
    current.selected_profile = selected_profile
    current.overrides = ConnectionOverrides(
        url=url,
        host=host,
        port=port,
        username=username,
        password=password,
        database=database,
        connection_timeout=connection_timeout,
    )


@cli.command("help")
@click.pass_context
def help_command(ctx: click.Context) -> None:
    """Show the complete command tree."""

    click.echo(ctx.find_root().get_help())


@cli.command("use")
@click.argument("name", type=PROFILE_NAME)
@click.option("--path", type=PATH)
@click.pass_context
def use_profile(ctx: click.Context, name: ProfileName, path: Path | None) -> None:
    """Select a profile for the current directory."""

    current = runtime(ctx)
    binding = current.profile_service.bind(name, path)
    emit_success(name.value, {"profile": name.value, "path": str(binding.path)})


@cli.group()
def skill() -> None:
    """Inspect the project CLI contract."""


@skill.command("path")
def skill_path() -> None:
    """Print the repository skill document path."""

    emit_success(None, {"path": REDIS_CLI_SKILL_PATH})


cli.add_command(connection)
cli.add_command(hash)
cli.add_command(key)
cli.add_command(list_group)
cli.add_command(profile)
cli.add_command(server)
cli.add_command(set_group)
cli.add_command(string)
cli.add_command(zset)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return its stable process code."""

    arguments = tuple(sys.argv[1:] if argv is None else argv)
    result = cli.main(args=arguments, prog_name="db-redis", standalone_mode=False)
    return 0 if result is None else int(result)


__all__ = ["CliRuntime", "cli", "create_runtime", "main"]
