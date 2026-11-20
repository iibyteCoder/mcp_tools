"""Turning expected failures into one JSON envelope, always."""

from __future__ import annotations

from typing import TYPE_CHECKING

import click

from host_cli.domain.enums import ErrorCode, ExitCode
from host_cli.domain.errors import HostCliError
from host_cli.presentation.rendering import (
    emit,
    exit_code_for,
    failure_envelope,
    success_envelope,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from host_cli.json_types import JsonOutput


class CommandFailed(Exception):
    """Signals that a command already rendered its failure and wants to exit.

    A classified non-success is a *result*, not an exception: its output has to
    be rendered before the process ends. Carrying the exit code back to the
    group this way keeps the command body a straight line.
    """

    def __init__(self, exit_code: ExitCode) -> None:
        super().__init__(exit_code.name)
        self.exit_code = exit_code


def report(data: JsonOutput) -> None:
    """Render a successful payload."""

    emit(success_envelope(data))


def report_failure(data: JsonOutput | None, error: HostCliError) -> None:
    """Render a failed payload and stop the command with a failure exit code."""

    emit(failure_envelope(data, error))
    raise CommandFailed(exit_code_for(False))


def argument_failure(message: str, data: JsonOutput | None = None) -> None:
    """Render an argument-level failure and stop the command."""

    report_failure(data, HostCliError(ErrorCode.INVALID_ARGUMENT, message))


class HostCliGroup(click.Group):
    """Turn every expected failure into one JSON failure envelope.

    Click's default behaviour prints prose and a traceback. Because every
    consumer of this tool parses JSON, the group converts all of it -- usage
    errors, expected failures and unexpected exceptions alike -- into the same
    envelope shape, so a caller never has to parse human text to find out what
    happened.
    """

    def main(  # type: ignore[override]
        self,
        args: Sequence[str] | None = None,
        prog_name: str | None = None,
        complete_var: str | None = None,
        standalone_mode: bool = True,
        **extra: object,
    ) -> int:
        del complete_var, standalone_mode, extra
        try:
            result = self.invoke_as_callable(args=args, prog_name=prog_name)
            return 0 if result is None else int(str(result))
        except CommandFailed as stopped:
            return int(stopped.exit_code)
        except HostCliError as error:
            emit(failure_envelope(None, error))
            return int(exit_code_for(False))
        except click.exceptions.Exit as control:
            return int(control.exit_code)
        except click.ClickException as error:
            emit(
                failure_envelope(
                    None,
                    HostCliError(ErrorCode.INVALID_ARGUMENT, error.format_message()),
                )
            )
            return int(exit_code_for(False))
        except Exception as error:
            emit(
                failure_envelope(
                    None,
                    HostCliError(ErrorCode.INTERNAL_ERROR, f"internal error: {error}"),
                )
            )
            return int(exit_code_for(False))

    def invoke_as_callable(self, *, args: Sequence[str] | None, prog_name: str | None) -> object:
        """Run the tree with Click's standalone mode off, isolating one cast.

        Click overloads ``main`` on the ``standalone_mode`` literal, so mypy
        cannot pick a variant for a non-literal value. Containing that in one
        helper keeps the suppression out of the exception handling that matters.

        ``super().main`` is called deliberately, not ``click.Command.main``:
        naming the bound method of the same subclass would re-enter this
        override and recurse until the stack dies.
        """

        result: object = super().main(
            args=args,
            prog_name=prog_name,
            standalone_mode=False,
        )
        return result


__all__ = ["CommandFailed", "HostCliGroup", "argument_failure", "report", "report_failure"]
