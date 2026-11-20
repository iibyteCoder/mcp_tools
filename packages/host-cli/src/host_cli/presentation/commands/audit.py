"""The ``audit`` command: read back what this tool actually did."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import click

from host_cli.application.guard import audit_path
from host_cli.application.probe import count_by_category, count_by_status, read_audit
from host_cli.domain.enums import AuditStatus
from host_cli.presentation.failures import report
from host_cli.presentation.params import POSITIVE_INT

if TYPE_CHECKING:
    from host_cli.infrastructure.audit import AuditEntry
    from host_cli.json_types import JsonOutput

DEFAULT_RECENT_LIMIT: Final[int] = 20
"""How many entries ``audit show`` returns when none is requested."""

STATUS_CHOICES: Final[tuple[str, ...]] = tuple(status.value for status in AuditStatus)
"""Accepted values for ``--status``, taken from the enum so they cannot drift."""


@click.group("audit")
def audit_group() -> None:
    """Inspect the local record of what this tool was asked to do."""


@audit_group.command("summary")
def audit_summary() -> None:
    """Count entries by status and by danger category.

    This is the observation the guard needs in order to be judged at all: a rule
    that never fires may be useless, and one that fires constantly is training
    the operator to pass ``--force`` without reading.
    """

    path = audit_path()
    report(
        {
            "path": str(path),
            "status": {status.value: count for status, count in count_by_status(path).items()},
            "danger_categories": {category.value: count for category, count in count_by_category(path).items()},
        }
    )


@audit_group.command("show")
@click.option(
    "--limit",
    type=POSITIVE_INT,
    default=DEFAULT_RECENT_LIMIT,
    help="How many recent entries to show.",
)
@click.option(
    "--status",
    "status_filter",
    type=click.Choice(STATUS_CHOICES),
    default=None,
    help="Show only entries with this status.",
)
def audit_show(limit: int, status_filter: str | None) -> None:
    """List the most recent entries, newest first."""

    entries = read_audit(audit_path())
    if status_filter is not None:
        entries = [entry for entry in entries if entry.status.value == status_filter]
    selected = entries[-limit:]
    selected.reverse()
    report(
        {
            "count": len(selected),
            "entries": [_entry_document(entry) for entry in selected],
        }
    )


def _entry_document(entry: AuditEntry) -> JsonOutput:
    """Render one audit entry as a reviewable object."""

    document: JsonOutput = {
        "timestamp": entry.timestamp.isoformat(),
        "status": entry.status.value,
        "verdict": entry.verdict.value,
        "profile": entry.profile,
        "command": entry.command,
        "outcome": entry.outcome,
        "forced": entry.forced,
        "danger_categories": list(entry.danger_categories),
    }
    return document


__all__ = ["DEFAULT_RECENT_LIMIT", "STATUS_CHOICES", "audit_group"]
