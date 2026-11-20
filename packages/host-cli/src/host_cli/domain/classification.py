"""Classification of one raw ssh execution into exactly one outcome."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from host_cli.domain.enums import (
    CONNECTION_SIGNALS,
    DebugLogMarker,
    EvidenceStrength,
    HostKeyProblem,
    OutcomeKind,
    SshExitCode,
    StderrSignal,
)
from host_cli.domain.models import Outcome

if TYPE_CHECKING:
    from host_cli.domain.models import RawExecution

_EXIT_STATUS_PATTERN = re.compile(
    rf"{re.escape(DebugLogMarker.EXIT_STATUS.value)}(-?\d+)\s*$",
    re.MULTILINE,
)
"""Matches the ``debug1: Exit status N`` line OpenSSH writes after a session ends.

This line is the single most direct piece of evidence available: sshd relayed an
exit status or an ``exit-signal``, so the remote command is known to have
finished. It is the only way to tell a remote 255 from OpenSSH's own 255, and it
is why the transport redirects the debug log to its own file.
"""


def classify(execution: RawExecution) -> Outcome:
    """Decide which single outcome an execution represents.

    Evidence is read in one place, the ssh debug log, because that is where
    OpenSSH records its own view of the session. Precedence runs from the
    strongest fact to the weakest:

    1. the client never started;
    2. our own timeout expired;
    3. the host key was not trusted;
    4. an explicit exit status or exit signal was relayed;
    5. the transport complained and no status was ever relayed;
    6. nothing matched, so the outcome is a labelled fallback.
    """

    if execution.spawn_failed:
        return Outcome(OutcomeKind.SSH_CLIENT_UNAVAILABLE)
    if execution.timed_out:
        return Outcome(OutcomeKind.TIMEOUT)

    log = execution.debug_log

    host_key = _host_key_outcome(log)
    if host_key is not None:
        return host_key

    relayed = _relayed_status_outcome(log)
    if relayed is not None:
        return relayed

    session_failure = _session_failure_outcome(log)
    if session_failure is not None:
        return session_failure

    return _process_status_outcome(execution)


def _host_key_outcome(log: str) -> Outcome | None:
    """Return the host key verdict, or ``None`` when the key was accepted."""

    if StderrSignal.HOST_KEY_CHANGED.value in log:
        return Outcome(OutcomeKind.HOST_KEY_UNTRUSTED, host_key_problem=HostKeyProblem.CHANGED)
    if StderrSignal.HOST_KEY_VERIFICATION_FAILED.value in log:
        return Outcome(OutcomeKind.HOST_KEY_UNTRUSTED, host_key_problem=HostKeyProblem.UNKNOWN)
    return None


def _relayed_status_outcome(log: str) -> Outcome | None:
    """Return the outcome proved by a relayed exit status, or ``None``.

    ``Exit status -1`` is OpenSSH's marker for a relayed ``exit-signal``; every
    non-negative value is a real status sshd reported. Neither can be confused
    with OpenSSH's own failure code, which is what makes exit code 255 safe here.
    """

    match = _EXIT_STATUS_PATTERN.search(log)
    if match is None:
        return None
    status = int(match.group(1))
    if status == SshExitCode.KILLED_BY_SIGNAL:
        return Outcome(OutcomeKind.REMOTE_KILLED_BY_SIGNAL)
    if status == 0:
        return Outcome(OutcomeKind.SUCCESS)
    return Outcome(OutcomeKind.REMOTE_NONZERO_EXIT)


def _session_failure_outcome(log: str) -> Outcome | None:
    """Return the outcome for a session that never delivered a status.

    ``AUTHENTICATION_FAILED`` is checked first: "Permission denied" is the last
    line OpenSSH writes when every method was refused, and it only appears after
    the connection itself succeeded.
    """

    if StderrSignal.PERMISSION_DENIED.value in log:
        return Outcome(OutcomeKind.AUTHENTICATION_FAILED)
    if any(signal.value in log for signal in CONNECTION_SIGNALS):
        return Outcome(OutcomeKind.CONNECTION_FAILED)
    return None


def _process_status_outcome(execution: RawExecution) -> Outcome:
    """Fall back to the local process status when the log settled nothing.

    Only used when no exit status was relayed, which normally means the debug
    log was missing. Zero and OpenSSH's own 255 are the only values with a
    meaning here; anything else is an unexplained failure and is marked as such.
    """

    if execution.exit_code == 0:
        return Outcome(OutcomeKind.SUCCESS, EvidenceStrength.FALLBACK)
    if execution.exit_code == SshExitCode.TRANSPORT_ERROR:
        return Outcome(OutcomeKind.CONNECTION_FAILED, EvidenceStrength.FALLBACK)
    return Outcome(OutcomeKind.CONNECTION_FAILED, EvidenceStrength.FALLBACK)


__all__ = ["classify"]
