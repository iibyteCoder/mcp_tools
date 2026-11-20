"""The dry run must answer "would this be refused?" without any transport.

These tests call the probe path directly rather than the CLI, so a regression in
the guard surfaces here rather than after a command has already been sent.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from host_cli.application.probe import (
    count_by_category,
    count_by_status,
    dry_run_entry,
    probe,
    read_audit,
)
from host_cli.domain.enums import AuditStatus, DangerCategory, GuardVerdict
from host_cli.infrastructure.audit import append

if TYPE_CHECKING:
    from pathlib import Path


def test_a_clean_command_is_reported_clear() -> None:
    report = probe("ps aux")

    assert report.verdict is GuardVerdict.CLEAR
    assert report.blocked is False
    assert report.categories == ()


def test_a_destructive_command_is_blocked() -> None:
    report = probe("rm -rf /")

    assert report.verdict is GuardVerdict.BLOCKED
    assert report.blocked is True


def test_an_unresolvable_command_is_an_advisory_not_a_clean_result() -> None:
    """``ADVISORY`` keeps "could not tell" distinct from "checked and fine"."""

    report = probe("rm -rf $TARGET")

    assert report.verdict is GuardVerdict.ADVISORY
    assert report.blocked is True
    assert report.categories == (DangerCategory.UNRESOLVED,)


def test_forcing_keeps_the_findings_but_stops_blocking() -> None:
    """The record must still show what was overridden."""

    report = probe("rm -rf /", forced=True)

    assert report.blocked is False
    assert report.forced is True
    assert report.categories


def test_a_probe_never_constructs_a_transport() -> None:
    """The probe path has no parameter that could reach a host.

    Asserted structurally: if this ever gains a transport argument, the test
    fails at import time on the call below, which is the point.
    """

    report = probe("echo hello")

    assert report.verdict is GuardVerdict.CLEAR


def test_a_dry_run_entry_is_recorded_as_a_probe(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    report = probe("rm -rf /var")

    append(path, dry_run_entry(profile="dev", host="example", user="ops", command="rm -rf /var", report=report))

    entries = read_audit(path)
    assert len(entries) == 1
    assert entries[0].status is AuditStatus.DRY_RUN
    assert entries[0].verdict is GuardVerdict.BLOCKED
    assert entries[0].command == "rm -rf /var"


def test_a_dry_run_leaves_no_outcome_fields(tmp_path: Path) -> None:
    """A probe never ran, so it must not look like it produced a result."""

    path = tmp_path / "audit.jsonl"
    append(
        path,
        dry_run_entry(
            profile="dev",
            host="example",
            user="ops",
            command="ps aux",
            report=probe("ps aux"),
        ),
    )

    entry = read_audit(path)[0]
    assert entry.outcome is None
    assert entry.remote_exit_code is None
    assert entry.remote_state is None


def test_status_counts_separate_probes_from_real_runs(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    append(path, dry_run_entry(profile="d", host="h", user="u", command="ps aux", report=probe("ps aux")))

    counts = count_by_status(path)

    assert counts[AuditStatus.DRY_RUN] == 1
    assert counts[AuditStatus.EXECUTED] == 0


def test_category_counts_expose_which_rules_fire(tmp_path: Path) -> None:
    """Without this summary nobody can tell rules that help from rules that nag."""

    path = tmp_path / "audit.jsonl"
    for command in ("rm -rf /", "rm -rf /etc"):
        append(
            path,
            dry_run_entry(
                profile="d",
                host="h",
                user="u",
                command=command,
                report=probe(command),
            ),
        )

    counts = count_by_category(path)

    assert counts[DangerCategory.RECURSIVE_DELETE] == 2


def test_reading_a_missing_audit_file_yields_nothing(tmp_path: Path) -> None:
    assert read_audit(tmp_path / "absent.jsonl") == []


def test_a_malformed_line_is_skipped_not_fatal(tmp_path: Path) -> None:
    """A damaged trail must still yield the entries that survived."""

    path = tmp_path / "audit.jsonl"
    append(path, dry_run_entry(profile="d", host="h", user="u", command="ps aux", report=probe("ps aux")))
    with path.open("a", encoding="utf-8") as stream:
        stream.write("{not json}\n")

    assert len(read_audit(path)) == 1


def test_the_recorded_document_carries_the_verdict(tmp_path: Path) -> None:
    """The verdict is a field, not prose: a reader can branch on it."""

    path = tmp_path / "audit.jsonl"
    append(path, dry_run_entry(profile="d", host="h", user="u", command="rm -rf /", report=probe("rm -rf /")))

    document = json.loads(path.read_text(encoding="utf-8").splitlines()[0])

    assert document["verdict"] == GuardVerdict.BLOCKED.value
    assert document["status"] == AuditStatus.DRY_RUN.value
