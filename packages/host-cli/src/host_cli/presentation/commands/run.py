"""The ``run`` command: send one command, report one result."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import click

from host_cli.application.guard import (
    approvals_path_of,
    gate,
    inspect,
    predict,
    rate_path_of,
    record_blocked,
    record_dry_run,
    record_executed,
)
from host_cli.application.guard import (
    request_approval as request_approval_for,
)
from host_cli.application.profile_service import ProfileService
from host_cli.application.run_service import run_command
from host_cli.domain.enums import OUTCOME_ERROR_CODES
from host_cli.domain.errors import HostCliError
from host_cli.domain.models import InvocationLimits
from host_cli.infrastructure.credentials import PasswordStore
from host_cli.infrastructure.profile_store import ProfileStore
from host_cli.presentation.failures import argument_failure, report, report_failure
from host_cli.presentation.params import POSITIVE_SECONDS, PROFILE_NAME
from host_cli.presentation.rendering import approval_document, dry_run_document, run_document

if TYPE_CHECKING:
    from db_cli_kit.profiles import ProfileName
    from host_cli.domain.models import GatePrediction, ProfileRecord, RunResult

DEBUG_LOG_FILE_NAME = "ssh.log"
"""Name of the per-invocation ssh debug log inside the temporary workspace."""


@click.command("run")
@click.argument("command", type=click.STRING)
@click.option("--profile", "profile_name", type=PROFILE_NAME, required=True, help="Which saved host to use.")
@click.option("--timeout", type=POSITIVE_SECONDS, default=None, help="Override the command bound in seconds.")
@click.option(
    "--force",
    is_flag=True,
    help="Run even when the guard flags the command, and record that it was forced.",
)
@click.option(
    "--dry-run",
    "dry_run",
    is_flag=True,
    help="Report what the guard decides without sending anything to the host.",
)
@click.option(
    "--request-approval",
    "request_approval",
    is_flag=True,
    help="Issue an approval for this command and print its token, without running it.",
)
@click.option(
    "--approve",
    "approval_token",
    default=None,
    metavar="TOKEN",
    help="Token from --request-approval that authorises this exact command.",
)
def run_group(
    command: str,
    profile_name: ProfileName,
    timeout: float | None,
    force: bool,
    dry_run: bool,
    request_approval: bool,
    approval_token: str | None,
) -> None:
    """Run one command on a saved host.

    The command reaches the remote shell exactly as written, so quoting, pipes
    and redirections are the caller's responsibility, and this tool never adds a
    wrapper of its own.

    Three gates stand between the command and the host, and each has its own
    escape:

    A command flagged as irreversible -- a recursive forced delete of a whole
    tree, a raw disk write, a power command, anything that removes the way back
    in -- is refused unless --force is given.

    A profile marked read-only refuses anything that is not inspection, and has
    no override of its own: mark the profile writable when the machine genuinely
    must change.

    A profile marked as requiring approval refuses every run until a token from
    --request-approval is passed with --approve. The token is bound to the exact
    command and expires, so it cannot become a standing permission.

    Every attempt is appended to the local audit log, including the ones that
    never ran.
    """

    if not command.strip():
        argument_failure("command must not be empty")
    if request_approval and approval_token is not None:
        argument_failure("--request-approval and --approve cannot be combined")
    if request_approval and dry_run:
        argument_failure("--request-approval and --dry-run cannot be combined")

    service = ProfileService(ProfileStore(), PasswordStore())
    record = service.record(profile_name)

    if request_approval:
        approval = request_approval_for(
            record=record,
            command=command,
            approvals_path=approvals_path_of(),
        )
        report(approval_document(approval))
        return

    verdict = inspect(command, forced=force)

    if dry_run:
        _report_dry_run(
            record=record, command=command, prediction=predict(record=record, command=command, forced=force)
        )
        return

    try:
        allowed = gate(
            record=record,
            command=command,
            forced=force,
            approval_token=approval_token,
            approvals_path=approvals_path_of(),
            rate_path=rate_path_of(),
        )
    except HostCliError as failure:
        record_blocked(record=record, command=command, report=verdict, error=failure)
        report_failure(None, failure)

    limits = InvocationLimits(command_timeout=timeout if timeout is not None else record.settings.command_timeout)
    with tempfile.TemporaryDirectory(prefix="host-cli-") as workspace:
        result = run_command(
            record,
            command,
            limits=limits,
            passwords=PasswordStore(),
            debug_log_path=Path(workspace) / DEBUG_LOG_FILE_NAME,
            forced=force,
            verdict=allowed.verdict,
        )

    audit_status = record_executed(result, record)
    data = run_document(result, audit_status=audit_status)

    if result.outcome.kind.is_success:
        report(data)
        return
    report_failure(data, _outcome_error(result))


def _report_dry_run(
    *,
    record: ProfileRecord,
    command: str,
    prediction: GatePrediction,
) -> None:
    """Report what every gate would decide, for a command that will not be sent.

    The probe is recorded too: a rehearsal that leaves no trace would read
    identically to a command that was never attempted.
    """

    audit_status = record_dry_run(record=record, command=command, report=prediction.report)
    report(
        dry_run_document(
            record=record,
            command=command,
            prediction=prediction,
            audit_status=audit_status,
        )
    )


def _outcome_error(result: RunResult) -> HostCliError:
    """Build the failure payload for a classified non-success outcome.

    The structured fields carry the evidence a consumer must act on -- which host
    key problem was seen, which fingerprint, whether the remote command may still
    be running -- instead of leaving it to be read out of prose.
    """

    return HostCliError(
        OUTCOME_ERROR_CODES[result.outcome.kind],
        _outcome_message(result),
        host_key_problem=result.outcome.host_key_problem,
        fingerprint=result.fingerprint,
        debug_log_tail=result.debug_log_tail,
    )


def _outcome_message(result: RunResult) -> str:
    """Describe a non-success outcome without implying a cause that was not proven."""

    if result.remote_exit_code is not None:
        return f"remote command exited with status {result.remote_exit_code}"
    return result.outcome.kind.value.replace("_", " ")


__all__ = ["DEBUG_LOG_FILE_NAME", "run_group"]
