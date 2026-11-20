"""Orchestration of one remote invocation from profile to finished result."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from host_cli.domain.classification import classify
from host_cli.domain.danger import find_dangers
from host_cli.domain.enums import DebugLogMarker, EvidenceStrength, GuardVerdict, OutcomeKind, RemoteState
from host_cli.domain.models import InvocationLimits, Outcome, ProfileRecord, RawExecution, RunResult
from host_cli.domain.streams import capture_stream
from host_cli.infrastructure.credentials import askpass_session, python_interpreter
from host_cli.infrastructure.ssh_argv import build_plan
from host_cli.infrastructure.ssh_runner import execute

if TYPE_CHECKING:
    from pathlib import Path

    from host_cli.infrastructure.credentials import PasswordStore

DEBUG_LOG_TAIL_LINES: Final[int] = 20
"""Debug log lines kept when the observed evidence did not settle the outcome."""

VALIDATION_COMMAND: Final[str] = "true"
"""The command a validation run sends.

``true`` is the smallest command that proves reachability, host key and
credentials all work while changing nothing. It is the one command this tool
picks on the operator's behalf, and only for ``profile validate`` -- there is no
other command it could sensibly choose.
"""

_ABANDONED_OUTCOMES: Final[frozenset[OutcomeKind]] = frozenset({OutcomeKind.TIMEOUT, OutcomeKind.CONNECTION_FAILED})
"""Outcomes where an authenticated session may have left a process running."""

_EXIT_CODE_OUTCOMES: Final[frozenset[OutcomeKind]] = frozenset({OutcomeKind.SUCCESS, OutcomeKind.REMOTE_NONZERO_EXIT})
"""Outcomes for which the host reported a real exit code.

A signal kill is excluded: OpenSSH reports ``-1`` for it, which is its own
marker rather than a status sshd relayed.
"""


def run_command(
    record: ProfileRecord,
    command: str,
    *,
    limits: InvocationLimits,
    passwords: PasswordStore,
    debug_log_path: Path,
    forced: bool = False,
    verdict: GuardVerdict = GuardVerdict.CLEAR,
) -> RunResult:
    """Execute ``command`` on the profile's host and report the classified outcome.

    The only place that knows the order: resolve the credential, build the plan,
    execute it, classify the result, then render the captured bytes. Each of
    those steps lives in its own module.

    ``forced`` and ``verdict`` are carried through only so the result records how
    the guard was satisfied; neither changes how the command runs.
    """

    password = passwords.read(record.name)
    plan = build_plan(
        record.settings,
        limits,
        command,
        debug_log_path,
        password_available=password is not None,
    )

    if password is None:
        execution = execute(plan, limits)
    else:
        with askpass_session(password, python_interpreter()) as session:
            execution = execute(plan, limits, extra_environment=session.environment)

    return assemble(record, command, classify(execution), execution, forced=forced, verdict=verdict)


def validate_profile(
    record: ProfileRecord,
    *,
    limits: InvocationLimits,
    passwords: PasswordStore,
    debug_log_path: Path,
) -> RunResult:
    """Check that a profile can reach, trust and authenticate to its host.

    Delegates to the ordinary run path with a fixed command, so validation can
    never diverge from what a real invocation would do. A separate code path
    would eventually disagree with the real one about credentials or host keys,
    which is exactly what a validation is supposed to catch.
    """

    return run_command(
        record,
        VALIDATION_COMMAND,
        limits=limits,
        passwords=passwords,
        debug_log_path=debug_log_path,
    )


def remote_exit_code_for(outcome: Outcome, execution: RawExecution) -> int | None:
    """Return the remote exit code, and only when the host actually supplied one.

    A signal kill arrives as OpenSSH's own ``-1`` marker rather than a number
    sshd reported, so it must not be presented as an exit code. Anything that
    stopped before reaching the host has no exit code at all.
    """

    if outcome.kind in _EXIT_CODE_OUTCOMES:
        return execution.exit_code
    return None


def assemble(
    record: ProfileRecord,
    command: str,
    outcome: Outcome,
    execution: RawExecution,
    *,
    forced: bool = False,
    verdict: GuardVerdict = GuardVerdict.CLEAR,
) -> RunResult:
    """Combine a classification with the evidence it was derived from."""

    return RunResult(
        profile=record.name,
        command=command,
        outcome=outcome,
        remote_exit_code=remote_exit_code_for(outcome, execution),
        remote_state=remote_state_for(outcome, execution.debug_log),
        duration_ms=execution.duration_ms,
        stdout=capture_stream(execution.stdout, execution.stdout_dropped),
        stderr=capture_stream(execution.stderr, execution.stderr_dropped),
        fingerprint=host_key_fingerprint(execution.debug_log),
        debug_log_tail=insufficient_evidence_tail(outcome, execution),
        danger_categories=tuple(finding.category for finding in find_dangers(command)),
        forced=forced,
        verdict=verdict,
    )


def remote_state_for(outcome: Outcome, debug_log: str) -> RemoteState:
    """Report what is known about the remote command after the invocation ends.

    The three states call for different reactions, so they stay distinct. A
    command that never started left no trace. A completed one is finished. One
    whose session authenticated and was then abandoned may still be running, so
    the operator must check before retrying.
    """

    if outcome.kind.remote_ran:
        return RemoteState.COMPLETED
    if outcome.kind in _ABANDONED_OUTCOMES and DebugLogMarker.AUTHENTICATED.value in debug_log:
        return RemoteState.UNKNOWN
    return RemoteState.NOT_STARTED


def host_key_fingerprint(debug_log: str) -> str | None:
    """Extract the host key fingerprint OpenSSH reported, if it got that far."""

    for line in debug_log.splitlines():
        index = line.find(DebugLogMarker.HOST_KEY.value)
        if index >= 0:
            return line[index + len(DebugLogMarker.HOST_KEY.value) :].strip()
    return None


def insufficient_evidence_tail(outcome: Outcome, execution: RawExecution) -> tuple[str, ...]:
    """Keep a short log tail only when the outcome was decided by fallback.

    A decisive classification needs no supporting log, so shipping twenty lines
    of ssh chatter for every failure would bury the signal in noise.
    """

    if outcome.evidence is EvidenceStrength.DECISIVE or not execution.debug_log:
        return ()
    return tuple(execution.debug_log.splitlines()[-DEBUG_LOG_TAIL_LINES:])


__all__ = [
    "DEBUG_LOG_TAIL_LINES",
    "assemble",
    "host_key_fingerprint",
    "insufficient_evidence_tail",
    "remote_state_for",
    "run_command",
]
