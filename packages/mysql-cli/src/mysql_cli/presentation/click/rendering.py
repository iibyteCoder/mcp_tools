"""JSON output and top-level Click exception handling."""

from __future__ import annotations

from typing import TYPE_CHECKING

import click

from mysql_cli.application.errors import CliFailure
from mysql_cli.application.profile import ProfileServiceError
from mysql_cli.application.results import DiagnosticMetadata, ErrorBody, ErrorEnvelope, SuccessEnvelope
from mysql_cli.application.runner import CliRuntime, CommandData
from mysql_cli.domain.command import CommandRequest, OutputMode
from mysql_cli.ports.profile_store import ProfileStoreError
from mysql_cli.presentation.click.failures import (
    cancelled_failure,
    click_failure,
    client_failure,
    internal_failure,
    profile_service_failure,
    profile_store_failure,
)
from mysql_cli.shared.json_codec import encode_json_document
from mysql_client import ClientError

if TYPE_CHECKING:
    from collections.abc import Sequence


class JsonClickGroup(click.Group):
    """Run Click in non-standalone mode and render all failures as JSON."""

    def main(  # type: ignore[override]
        self,
        args: Sequence[str] | None = None,
        prog_name: str | None = None,
        complete_var: str | None = None,
        standalone_mode: bool = True,
        **extra: object,
    ) -> int | None:
        provided_runtime = extra.get("obj")
        runtime = provided_runtime if isinstance(provided_runtime, CliRuntime) else CliRuntime.create_default()
        extra["obj"] = runtime
        try:
            raw_result = super().main(
                args=args,
                prog_name=prog_name,
                complete_var=complete_var,
                standalone_mode=False,
                **extra,
            )
            result = None if raw_result is None else int(raw_result)
        except click.exceptions.Exit as control:
            result = int(control.exit_code)
        except CliFailure as failure:
            result = render_failure(failure, runtime)
        except ProfileStoreError as error:
            result = render_failure(profile_store_failure(error), runtime)
        except ProfileServiceError as error:
            result = render_failure(profile_service_failure(error), runtime)
        except ClientError as error:
            result = render_failure(client_failure(error), runtime)
        except click.Abort:
            result = render_failure(cancelled_failure(), runtime)
        except click.ClickException as error:
            result = render_failure(click_failure(error), runtime)
        except KeyboardInterrupt:
            result = render_failure(cancelled_failure(), runtime)
        except Exception:
            result = render_failure(internal_failure(), runtime)
        if standalone_mode and result not in (None, 0):
            raise SystemExit(int(result))
        return result


def write_success(data: CommandData, request: CommandRequest) -> None:
    envelope = SuccessEnvelope(
        ok=True,
        data=data,
        meta=DiagnosticMetadata(
            command_group=request.group,
            action=request.action,
            input_source=request.sql_input.source if request.sql_input is not None else None,
        ),
    )
    click.echo(encode_json_document(envelope), nl=False)


def write_failure(failure: CliFailure, request: CommandRequest | None) -> None:
    envelope = ErrorEnvelope(
        ok=False,
        error=ErrorBody(
            code=failure.code,
            message=failure.message,
            retryable=failure.retryable,
            details=failure.details,
            write_outcome=failure.write_outcome,
            differences=failure.differences,
        ),
        meta=DiagnosticMetadata(
            command_group=request.group if request is not None else None,
            action=request.action if request is not None else None,
            input_source=request.sql_input.source if request is not None and request.sql_input is not None else None,
            output_mode=OutputMode.JSON,
        ),
    )
    click.echo(encode_json_document(envelope), nl=False)


def render_failure(failure: CliFailure, runtime: CliRuntime) -> int:
    write_failure(failure, runtime.request)
    return int(failure.exit_code)


__all__ = ["JsonClickGroup", "render_failure", "write_failure", "write_success"]
