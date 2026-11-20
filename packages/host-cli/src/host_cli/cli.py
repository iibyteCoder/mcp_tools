"""Click command tree for host-cli."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import click

from db_cli_kit.stdio import enforce_utf8_stdio
from host_cli import __version__
from host_cli.domain.enums import CommandGroup
from host_cli.presentation.commands.audit import audit_group
from host_cli.presentation.commands.profile import profile_group
from host_cli.presentation.commands.run import run_group
from host_cli.presentation.failures import HostCliGroup, report

if TYPE_CHECKING:
    from collections.abc import Sequence


@click.group(
    cls=HostCliGroup,
    context_settings={"help_option_names": ["-h", "--help"], "max_content_width": 120},
)
@click.version_option(version=__version__, prog_name="host-cli", message="%(prog)s %(version)s")
def cli() -> None:
    """Send one command to a configured host and report exactly what came back.

    The remote command is a single argument handed to the remote shell verbatim;
    this tool does not parse, wrap, rewrite or interpret it.
    """


@click.command("skill")
def skill_command() -> None:
    """Print where the host-cli Skill document is expected to be installed.

    The skill file lives in this repository; each agent runtime reads it from its
    own installation root. Printing both destinations avoids guessing, and
    printing whether each already exists says whether anything is left to do.
    """

    from host_cli.skill_paths import resolve_host_cli_skill_paths

    paths = resolve_host_cli_skill_paths()
    report(
        {
            "skill": "host-cli",
            "targets": [
                {"runtime": "codex", "path": str(paths.codex), "installed": paths.codex.exists()},
                {"runtime": "dsh", "path": str(paths.dsh), "installed": paths.dsh.exists()},
            ],
        }
    )


cli.add_command(profile_group, CommandGroup.PROFILE.value)
cli.add_command(run_group, CommandGroup.RUN.value)
cli.add_command(audit_group, CommandGroup.AUDIT.value)
cli.add_command(skill_command)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return its process exit code."""

    enforce_utf8_stdio()
    arguments = tuple(sys.argv[1:] if argv is None else argv)
    result = cli.main(args=arguments, prog_name="host-cli", standalone_mode=False)
    return 0 if result is None else int(result)


__all__ = ["cli", "main"]
