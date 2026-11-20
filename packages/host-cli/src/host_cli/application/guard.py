"""Deciding whether a command may leave the machine, and recording what happened.

Three gates stand between a caller and the host, and they answer different
questions:

- the **danger** gate asks "is this irreversible";
- the **intent** gate asks "is this a change at all", for profiles marked
  read-only;
- the **approval** gate asks "did a human agree to this one".

They are composed here rather than scattered through the CLI because the order
matters: a command that would be refused anyway should never generate an approval
request, and an approval should never be checked for a command that cannot run.

The audit trail lives here too, because it records the outcome of these gates and
splitting it would let the gates change without the record noticing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from host_cli.domain.danger import find_dangers
from host_cli.domain.enums import (
    ApprovalState,
    AuditWriteStatus,
    CommandIntent,
    DangerCategory,
    ErrorCode,
    GuardVerdict,
)
from host_cli.domain.errors import HostCliError
from host_cli.domain.intent import classify_intent
from host_cli.domain.models import DangerReport, GatePrediction
from host_cli.infrastructure.approvals import check as check_approval
from host_cli.infrastructure.approvals import issue as issue_approval
from host_cli.infrastructure.audit import (
    append,
    build_blocked_entry,
    build_dry_run_entry,
    build_entry,
)
from host_cli.infrastructure.rate_limit import consume as consume_rate
from host_cli.infrastructure.rate_limit import remaining as remaining_rate

if TYPE_CHECKING:
    from pathlib import Path

    from host_cli.domain.models import ProfileRecord, RunResult
    from host_cli.infrastructure.approvals import Approval

_REPORT_SEPARATOR: Final[str] = ", "
"""How multiple matched categories are joined in the failure message."""


def inspect(command: str, *, forced: bool) -> DangerReport:
    """Return the guard's verdict for one command.

    Three outcomes, not two. A command that matched nothing is ``CLEAR``. One
    that matched an irreversible shape is ``BLOCKED``. One that matched only
    ``UNRESOLVED`` -- a destructive command whose target is decided at run time --
    is ``ADVISORY``: still requiring ``--force``, but labelled so a caller knows
    the guard could not see rather than saw and approved.

    With ``forced`` set the findings are still collected, because the record
    should show what the caller overrode rather than nothing at all.
    """

    findings = find_dangers(command)
    if not findings:
        return DangerReport(findings=(), verdict=GuardVerdict.CLEAR)

    decisive = any(finding.category is not DangerCategory.UNRESOLVED for finding in findings)
    verdict = GuardVerdict.BLOCKED if decisive else GuardVerdict.ADVISORY
    return DangerReport(findings=findings, verdict=verdict, forced=forced)


def blocked_error(report: DangerReport) -> HostCliError:
    """Build the failure a blocked command returns.

    The matched categories and the matched text are both reported, so a caller
    can tell a true positive from an over-eager pattern without guessing which
    words triggered it. An advisory verdict says so explicitly, because "I could
    not resolve this" is a different message from "this is destructive".
    """

    categories = _REPORT_SEPARATOR.join(category.value for category in report.categories)
    reason = "unresolved" if report.verdict is GuardVerdict.ADVISORY else "dangerous"
    return HostCliError(
        ErrorCode.DANGEROUS_COMMAND,
        f"refusing to run an unforced {reason} command ({categories})",
        danger_excerpts=tuple(finding.excerpt for finding in report.findings),
    )


def read_only_error(command: str, intent: CommandIntent) -> HostCliError:
    """Build the failure a read-only profile returns for a mutating command."""

    return HostCliError(
        ErrorCode.READ_ONLY_VIOLATION,
        f"profile is read-only and this command is a {intent.value}",
        danger_excerpts=(command,),
    )


def approval_error(state: ApprovalState) -> HostCliError:
    """Build the failure a profile needing approval returns.

    Each state gets its own message because the remedy differs: request an
    approval, wait for it to be re-issued, or check that the right command is
    being run.
    """

    messages = {
        ApprovalState.REQUIRED: (
            "this profile requires an approval for each run: "
            "the command was refused because no matching approval was supplied"
        ),
        ApprovalState.EXPIRED: "the approval has expired and must be issued again",
        ApprovalState.MISMATCH: "the approval was issued for a different command",
        ApprovalState.GRANTED: "the approval was accepted",
    }
    return HostCliError(ErrorCode.APPROVAL_REQUIRED, messages[state])


def rate_limited_error(limit: int) -> HostCliError:
    """Build the failure a profile over its rate ceiling returns."""

    return HostCliError(
        ErrorCode.RATE_LIMITED,
        f"profile allows at most {limit} commands per minute and the ceiling is reached",
    )


def gate(
    *,
    record: ProfileRecord,
    command: str,
    forced: bool,
    approval_token: str | None,
    approvals_path: Path,
    rate_path: Path,
) -> DangerReport:
    """Apply every gate, in order, and return the danger report when allowed.

    Raises ``HostCliError`` on the first gate that refuses. The gates are ordered
    cheapest and most fundamental first: a command that cannot run at all should
    not consume a rate slot or an approval.
    """

    report = inspect(command, forced=forced)
    if report.blocked:
        raise blocked_error(report)

    if record.settings.read_only:
        intent = classify_intent(command)
        if intent is not CommandIntent.INSPECTION:
            raise read_only_error(command, intent)

    if record.settings.requires_approval:
        _require_approval(
            record=record,
            command=command,
            token=approval_token,
            approvals_path=approvals_path,
        )

    if not consume_rate(
        path=rate_path,
        profile=record.name,
        limit=record.settings.max_commands_per_minute,
    ):
        raise rate_limited_error(record.settings.max_commands_per_minute)

    return report


def request_approval(
    *,
    record: ProfileRecord,
    command: str,
    approvals_path: Path,
) -> Approval:
    """Issue an approval for one command on one profile.

    The command is checked against the danger guard first: issuing an approval for
    something that could never run would only invite a second attempt.
    """

    report = inspect(command, forced=True)
    if report.blocked:
        raise blocked_error(report)
    return issue_approval(path=approvals_path, profile=record.name, command=command)


def predict(
    *,
    record: ProfileRecord,
    command: str,
    forced: bool,
) -> GatePrediction:
    """Say which gate *would* refuse this command, without running anything.

    A dry run that only consulted the danger guard would answer a narrower
    question than it appears to: a command can be perfectly safe and still be
    refused because the profile is read-only or approval-gated. Reporting
    ``would_block: false`` there would be wrong in the most corrosive way -- the
    caller would check first, see green, and then be refused.

    The approval gate is reported as requiring a token rather than as a failure:
    it is satisfiable, and the caller can act on that. The rate ceiling is
    measured but never consumed, because a probe must not cost a slot.
    """

    report = inspect(command, forced=forced)
    if report.blocked:
        return GatePrediction(report=report, reason=ErrorCode.DANGEROUS_COMMAND)

    if record.settings.read_only and classify_intent(command) is CommandIntent.MUTATION:
        return GatePrediction(report=report, reason=ErrorCode.READ_ONLY_VIOLATION)

    if record.settings.requires_approval:
        return GatePrediction(report=report, reason=ErrorCode.APPROVAL_REQUIRED)

    limit = record.settings.max_commands_per_minute
    if limit > 0 and remaining_rate(path=rate_path_of(), profile=record.name, limit=limit) <= 0:
        return GatePrediction(report=report, reason=ErrorCode.RATE_LIMITED)

    return GatePrediction(report=report, reason=None)


def _require_approval(
    *,
    record: ProfileRecord,
    command: str,
    token: str | None,
    approvals_path: Path,
) -> None:
    """Raise unless ``token`` authorises this exact command on this profile."""

    if token is None:
        raise approval_error(ApprovalState.REQUIRED)
    state = check_approval(
        path=approvals_path,
        profile=record.name,
        command=command,
        token=token,
    )
    if state is not ApprovalState.GRANTED:
        raise approval_error(state)


def record_executed(result: RunResult, record: ProfileRecord) -> AuditWriteStatus:
    """Append the audit line for a command that ran."""

    return append(
        audit_path(),
        build_entry(
            result=result,
            host=record.settings.host,
            user=record.settings.user,
            forced=result.forced,
        ),
    )


def record_blocked(
    *,
    record: ProfileRecord,
    command: str,
    report: DangerReport,
    error: HostCliError | None = None,
) -> AuditWriteStatus:
    """Append the audit line for a command a gate refused."""

    return append(
        audit_path(),
        build_blocked_entry(
            profile=record.name.value,
            host=record.settings.host,
            user=record.settings.user,
            command=command,
            categories=tuple(category.value for category in report.categories),
            verdict=report.verdict,
            reason=None if error is None else error.code.value,
        ),
    )


def record_dry_run(
    *,
    record: ProfileRecord,
    command: str,
    report: DangerReport,
) -> AuditWriteStatus:
    """Append the audit line for a probe the caller chose not to execute.

    Recorded so a later reader can tell a rehearsal from a real run; without this
    line the trail would silently omit the fact that the guard was consulted.
    """

    return append(
        audit_path(),
        build_dry_run_entry(
            profile=record.name.value,
            host=record.settings.host,
            user=record.settings.user,
            command=command,
            categories=tuple(category.value for category in report.categories),
            verdict=report.verdict,
        ),
    )


def audit_path() -> Path:
    """Return the audit file location for the current user.

    Re-exported rather than imported at module scope so the tests can replace one
    name and have every caller see the replacement.
    """

    from host_cli.infrastructure import audit

    return audit.audit_path()


def approvals_path_of() -> Path:
    """Return the approval file location, beside the profile registry."""

    from host_cli.infrastructure.approvals import APPROVAL_FILE_NAME
    from host_cli.infrastructure.profile_store import default_registry_path

    return default_registry_path().parent / APPROVAL_FILE_NAME


def rate_path_of() -> Path:
    """Return the rate-limit file location, beside the profile registry."""

    from host_cli.infrastructure.profile_store import default_registry_path
    from host_cli.infrastructure.rate_limit import RATE_FILE_NAME

    return default_registry_path().parent / RATE_FILE_NAME


__all__ = [
    "approval_error",
    "approvals_path_of",
    "audit_path",
    "blocked_error",
    "gate",
    "inspect",
    "predict",
    "rate_limited_error",
    "rate_path_of",
    "read_only_error",
    "record_blocked",
    "record_dry_run",
    "record_executed",
    "request_approval",
]
