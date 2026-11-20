"""Dry-run probes: the guard must be answerable without touching a host.

A dry run exists so a caller can ask "would this be refused?" before committing
to the act. Everything here goes through the same classifier the real path uses,
with the transport never constructed, so a probe can never reach a machine.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from host_cli.application.guard import inspect
from host_cli.domain.enums import AuditStatus, DangerCategory, GuardVerdict
from host_cli.infrastructure.audit import (
    AuditEntry,
    append,
    build_dry_run_entry,
)

if TYPE_CHECKING:
    from pathlib import Path

    from host_cli.domain.models import DangerReport


def probe(command: str, *, forced: bool = False) -> DangerReport:
    """Return the guard's verdict for a command, without any transport.

    Kept separate from ``inspect`` only for emphasis: this is the entry point a
    dry run uses, and it is deliberately free of any parameter that could reach a
    host.
    """

    return inspect(command, forced=forced)


def dry_run_entry(
    *,
    profile: str,
    host: str,
    user: str,
    command: str,
    report: DangerReport,
) -> AuditEntry:
    """Build the audit record for one probe."""

    return build_dry_run_entry(
        profile=profile,
        host=host,
        user=user,
        command=command,
        categories=tuple(category.value for category in report.categories),
        verdict=report.verdict,
    )


def read_audit(path: Path) -> list[AuditEntry]:
    """Read back every audit line, newest last.

    Used by tests and by anyone asking "did anything actually run". A malformed
    line is skipped rather than aborting the read: a damaged trail should still
    yield the entries that survived.
    """

    entries: list[AuditEntry] = []
    if not path.exists():
        return entries
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            entries.append(_entry_from_document(json.loads(line)))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            continue
    return entries


def count_by_status(path: Path) -> dict[AuditStatus, int]:
    """Return how many entries fall in each status, for a quick summary."""

    counts = dict.fromkeys(AuditStatus, 0)
    for entry in read_audit(path):
        counts[entry.status] += 1
    return counts


def count_by_category(path: Path) -> dict[DangerCategory, int]:
    """Return how often each danger category was flagged.

    This is the observation the guard previously lacked: without it, nobody can
    tell whether the rules are catching real attempts or merely annoying the
    operator.
    """

    counts = dict.fromkeys(DangerCategory, 0)
    for entry in read_audit(path):
        for raw in entry.danger_categories:
            try:
                counts[DangerCategory(raw)] += 1
            except ValueError:
                continue
    return counts


def _entry_from_document(document: dict[str, object]) -> AuditEntry:
    """Rebuild one entry from its stored form.

    ``verdict`` is optional because the field was added after this file format
    already existed: entries written before it must stay readable, or adding a
    field would silently orphan the very evidence the file exists to preserve. A
    missing verdict is inferred from the status and the categories, which carry
    the same information less explicitly.
    """

    from datetime import datetime

    from host_cli.domain.enums import AuditField

    def text(key: AuditField) -> str:
        value = document[key.value]
        if not isinstance(value, str):
            raise TypeError(f"{key.value} is not text")
        return value

    def optional_int(key: AuditField) -> int | None:
        value = document.get(key.value)
        return value if isinstance(value, int) else None

    def optional_text(key: AuditField) -> str | None:
        value = document.get(key.value)
        return value if isinstance(value, str) else None

    raw_categories = document.get(AuditField.DANGER_CATEGORIES.value, [])
    categories = tuple(str(item) for item in raw_categories) if isinstance(raw_categories, list) else ()
    status = AuditStatus(text(AuditField.STATUS))

    return AuditEntry(
        timestamp=datetime.fromisoformat(text(AuditField.TIMESTAMP)),
        profile=text(AuditField.PROFILE),
        host=text(AuditField.HOST),
        user=text(AuditField.USER),
        command=text(AuditField.COMMAND),
        command_truncated=False,
        status=status,
        verdict=_verdict_of(document, status, categories),
        outcome=optional_text(AuditField.OUTCOME),
        remote_exit_code=optional_int(AuditField.REMOTE_EXIT_CODE),
        remote_state=optional_text(AuditField.REMOTE_STATE),
        duration_ms=optional_int(AuditField.DURATION_MS) or 0,
        stdout_bytes=optional_int(AuditField.STDOUT_BYTES) or 0,
        stderr_bytes=optional_int(AuditField.STDERR_BYTES) or 0,
        truncated_streams=bool(document.get(AuditField.TRUNCATED.value)),
        forced=bool(document.get(AuditField.FORCED.value)),
        danger_categories=categories,
        reason=optional_text(AuditField.REASON),
    )


def _verdict_of(
    document: dict[str, object],
    status: AuditStatus,
    categories: tuple[str, ...],
) -> GuardVerdict:
    """Return the stored verdict, inferring one for entries recorded before it."""

    from host_cli.domain.enums import AuditField

    stored = document.get(AuditField.VERDICT.value)
    if isinstance(stored, str):
        try:
            return GuardVerdict(stored)
        except ValueError:
            pass
    if status is AuditStatus.BLOCKED:
        decisive = any(category != DangerCategory.UNRESOLVED.value for category in categories)
        return GuardVerdict.BLOCKED if decisive else GuardVerdict.ADVISORY
    return GuardVerdict.CLEAR


__all__ = [
    "append",
    "count_by_category",
    "count_by_status",
    "dry_run_entry",
    "probe",
    "read_audit",
]
