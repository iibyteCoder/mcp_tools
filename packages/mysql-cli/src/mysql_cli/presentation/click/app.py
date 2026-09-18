"""Click root for the JSON-only MySQL CLI."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import click

from mysql_cli import __version__
from mysql_cli.application.runner import CliRuntime
from mysql_cli.presentation.click.commands import profile, schema, server, sql
from mysql_cli.presentation.click.rendering import JsonClickGroup
from mysql_cli.presentation.click.runtime import runtime
from mysql_cli.presentation.click.types import PROFILE_NAME

if TYPE_CHECKING:
    from collections.abc import Sequence

    from mysql_cli.domain.profile import ProfileName


@click.group(
    cls=JsonClickGroup,
    context_settings={"help_option_names": ["-h", "--help"], "max_content_width": 120},
)
@click.version_option(version=__version__, prog_name="db-mysql", message="%(prog)s %(version)s")
@click.option("--json", "json_output", is_flag=True, help="emit one JSON document")
@click.option("--profile", "selected_profile", type=PROFILE_NAME, help="select a profile for this invocation")
@click.pass_context
def cli(ctx: click.Context, json_output: bool, selected_profile: ProfileName | None) -> None:
    """JSON-only MySQL command line foundation."""

    del json_output
    current_runtime = runtime(ctx)
    current_runtime.selected_profile = selected_profile


@cli.command("help")
@click.pass_context
def help_command(ctx: click.Context) -> None:
    """Show the complete command tree."""

    click.echo(ctx.find_root().get_help())


cli.add_command(profile)
cli.add_command(server)
cli.add_command(schema)
cli.add_command(sql)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return a stable process exit code."""

    arguments = tuple(sys.argv[1:] if argv is None else argv)
    result = cli.main(args=arguments, prog_name="db-mysql", standalone_mode=False)
    return 0 if result is None else int(result)


__all__ = ["CliRuntime", "cli", "main"]
