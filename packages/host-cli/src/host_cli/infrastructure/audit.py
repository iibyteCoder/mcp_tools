"""The local audit trail: one line per invocation, appended after it finishes.

The record is written by the CLI because nothing else knows what the caller
asked for. On this host the remote side cannot answer that question either: the
tool runs without a pty, so `~/.bash_history` and `pam_tty_audit` see nothing,
and sshd's own log records the login but never the command. An audit trail here
is therefore the only place the command itself survives.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Final

from host_cli.domain.enums import AuditField, AuditStatus, AuditWriteStatus, GuardVerdict

if TYPE_CHECKING:
    from pathlib import Path

    from host_cli.domain.models import RunResult

AUDIT_FILE_NAME: Final[str] = "audit.jsonl"
"""One JSON object per line: appendable, greppable, and trivially tailed."""

AUDIT_DIRECTORY_NAME: Final[str] = "host-cli"

_MAX_COMMAND_PREVIEW: Final[int] = 4096
"""Commands are truncated for the record, and the truncation is recorded.

A silent truncation would make the audit trail disagree with what ran, which is
worse than a long line, so the preview keeps only the head and flags itself.
"""


@dataclass(frozen=True, slots=True)
class AuditEntry:
    """One invocation as recorded, whether it ran, was refused, or was a probe."""

    timestamp: datetime
    profile: str
    host: str
    user: str
    command: str
    command_truncated: bool
    status: AuditStatus
    verdict: GuardVerdict
    outcome: str | None
    remote_exit_code: int | None
    remote_state: str | None
    duration_ms: int
    stdout_bytes: int
    stderr_bytes: int
    truncated_streams: bool
    forced: bool
    danger_categories: tuple[str, ...]
    reason: str | None = None
    """Which gate refused the command, if it was refused.

    Recorded separately from ``danger_categories`` because the gates are not the
    same thing: a read-only refusal or a missing approval blocks a command that the
    danger guard considered perfectly safe, and a reader comparing the two needs to
    see which one acted.
    """


def audit_path() -> Path:
    """Return the audit file location for the current user."""

    from platformdirs import user_log_path

    return user_log_path(AUDIT_DIRECTORY_NAME) / AUDIT_FILE_NAME


def build_entry(
    *,
    result: RunResult,
    host: str,
    user: str,
    forced: bool,
) -> AuditEntry:
    """Build the record for one executed invocation."""

    command, truncated = _preview(result.command)
    return AuditEntry(
        timestamp=datetime.now(timezone.utc),
        profile=result.profile.value,
        host=host,
        user=user,
        command=command,
        command_truncated=truncated,
        status=AuditStatus.EXECUTED,
        verdict=result.verdict,
        outcome=result.outcome.kind.value,
        remote_exit_code=result.remote_exit_code,
        remote_state=result.remote_state.value,
        duration_ms=result.duration_ms,
        stdout_bytes=result.stdout.bytes,
        stderr_bytes=result.stderr.bytes,
        truncated_streams=result.stdout.truncated or result.stderr.truncated,
        forced=forced,
        danger_categories=tuple(category.value for category in result.danger_categories),
    )


def build_blocked_entry(
    *,
    profile: str,
    host: str,
    user: str,
    command: str,
    categories: tuple[str, ...],
    verdict: GuardVerdict,
    reason: str | None = None,
) -> AuditEntry:
    """Build the record for a command a gate refused.

    A refusal is recorded because it is evidence: it shows what was asked for and
    that nothing ran.
    """

    preview, truncated = _preview(command)
    return AuditEntry(
        timestamp=datetime.now(timezone.utc),
        profile=profile,
        host=host,
        user=user,
        command=preview,
        command_truncated=truncated,
        status=AuditStatus.BLOCKED,
        verdict=verdict,
        outcome=None,
        remote_exit_code=None,
        remote_state=None,
        duration_ms=0,
        stdout_bytes=0,
        stderr_bytes=0,
        truncated_streams=False,
        forced=False,
        danger_categories=categories,
        reason=reason,
    )


def build_dry_run_entry(
    *,
    profile: str,
    host: str,
    user: str,
    command: str,
    categories: tuple[str, ...],
    verdict: GuardVerdict,
) -> AuditEntry:
    """Build the record for a probe the caller chose not to execute.

    Without this line the trail would omit the fact that the guard was consulted
    and the run was intentionally skipped, which reads identically to a command
    that never happened.
    """

    preview, truncated = _preview(command)
    return AuditEntry(
        timestamp=datetime.now(timezone.utc),
        profile=profile,
        host=host,
        user=user,
        command=preview,
        command_truncated=truncated,
        status=AuditStatus.DRY_RUN,
        verdict=verdict,
        outcome=None,
        remote_exit_code=None,
        remote_state=None,
        duration_ms=0,
        stdout_bytes=0,
        stderr_bytes=0,
        truncated_streams=False,
        forced=False,
        danger_categories=categories,
    )


def append(path: Path, entry: AuditEntry) -> AuditWriteStatus:
    """Append one entry, returning whether it reached the disk.

    The caller has already run the command by the time this is called, so a
    failure can only be reported, never undone. Returning a status keeps a
    silent evidence gap from looking like a clean record.
    """

    line = json.dumps(_document(entry), ensure_ascii=False, separators=(",", ":")) + "\n"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(line)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError:
        return AuditWriteStatus.FAILED
    return AuditWriteStatus.WRITTEN


def _document(entry: AuditEntry) -> dict[str, object]:
    """Map one entry onto its wire field names."""

    return {
        AuditField.TIMESTAMP.value: entry.timestamp.isoformat(),
        AuditField.PROFILE.value: entry.profile,
        AuditField.HOST.value: entry.host,
        AuditField.USER.value: entry.user,
        AuditField.COMMAND.value: entry.command,
        AuditField.STATUS.value: entry.status.value,
        AuditField.VERDICT.value: entry.verdict.value,
        AuditField.OUTCOME.value: entry.outcome,
        AuditField.REMOTE_EXIT_CODE.value: entry.remote_exit_code,
        AuditField.REMOTE_STATE.value: entry.remote_state,
        AuditField.DURATION_MS.value: entry.duration_ms,
        AuditField.STDOUT_BYTES.value: entry.stdout_bytes,
        AuditField.STDERR_BYTES.value: entry.stderr_bytes,
        AuditField.TRUNCATED.value: entry.truncated_streams,
        AuditField.FORCED.value: entry.forced,
        AuditField.DANGER_CATEGORIES.value: list(entry.danger_categories),
        AuditField.REASON.value: entry.reason,
    }


def _preview(command: str) -> tuple[str, bool]:
    """Return the recorded command and whether it had to be shortened."""

    if len(command) <= _MAX_COMMAND_PREVIEW:
        return command, False
    return command[:_MAX_COMMAND_PREVIEW], True


__all__ = [
    "AUDIT_DIRECTORY_NAME",
    "AUDIT_FILE_NAME",
    "AuditEntry",
    "append",
    "audit_path",
    "build_blocked_entry",
    "build_dry_run_entry",
    "build_entry",
]
