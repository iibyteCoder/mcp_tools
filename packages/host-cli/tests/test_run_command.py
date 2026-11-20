"""End-to-end checks of the ``run`` command's guard wiring, without a host.

The real entry point is called -- ``host_cli.cli.main`` -- so the exit code, the
envelope and the guard wiring are all covered by the same path production uses.
The transport is never reached: every case either probes, is refused, or fails
before a session is built.

Standard streams are replaced by a small double that provides ``buffer`` and
``reconfigure``, because the real entry point reconfigures them. That double
exists only in tests; production code deliberately has no fallback for a stream
that cannot be reconfigured.
"""

from __future__ import annotations

import io
import json
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from db_cli_kit.profiles import ProfileName
from host_cli.cli import main
from host_cli.domain.enums import AuditStatus, GuardVerdict
from host_cli.domain.models import ProfileRecord, ProfileSettings
from host_cli.infrastructure.profile_store import ProfileStore

if TYPE_CHECKING:
    from pathlib import Path

    from pytest import MonkeyPatch

PROFILE_NAME = "dev"
HOST = "example"
USER = "operator"


class _StreamDouble:
    """A standard-stream stand-in that collects bytes and accepts reconfigure."""

    def __init__(self) -> None:
        self.buffer = io.BytesIO()

    def reconfigure(self, *, encoding: str) -> None:
        """Accept the entry point's UTF-8 request; nothing to change here."""

    def write(self, text: str) -> int:
        """Support incidental text writes from the framework."""

        self.buffer.write(text.encode("utf-8"))
        return len(text)

    def flush(self) -> None:
        """Match the text-stream protocol."""

    def decoded(self) -> str:
        """Return everything written so far as text."""

        return self.buffer.getvalue().decode("utf-8")


@dataclass(frozen=True, slots=True)
class Workspace:
    """The temporary storage this test drives the CLI against."""

    registry_path: Path
    audit_path: Path


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: MonkeyPatch) -> Workspace:
    """Redirect both storage seams into a temporary directory.

    Patching the path functions is the only portable approach: ``platformdirs``
    resolves the configuration directory per platform and ignores
    ``XDG_CONFIG_HOME`` on Windows.
    """

    registry_path = tmp_path / "profiles.json"
    audit_path = tmp_path / "audit.jsonl"
    monkeypatch.setattr(
        "host_cli.infrastructure.profile_store.default_registry_path",
        lambda: registry_path,
    )
    monkeypatch.setattr("host_cli.application.guard.audit_path", lambda: audit_path)
    return Workspace(registry_path=registry_path, audit_path=audit_path)


@pytest.fixture
def configured(workspace: Workspace) -> Workspace:
    """Store one profile into the temporary registry."""

    record = ProfileRecord(
        name=ProfileName(value=PROFILE_NAME),
        settings=ProfileSettings(host=HOST, user=USER),
    )
    ProfileStore(workspace.registry_path).update(lambda registry: registry.replace(record))
    return workspace


def invoke(
    monkeypatch: MonkeyPatch,
    *arguments: str,
) -> tuple[int, dict[str, object]]:
    """Run the real entry point and return its exit code with the envelope."""

    stdout = _StreamDouble()
    stderr = _StreamDouble()
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)

    exit_code = main(list(arguments))

    document = json.loads(stdout.decoded().strip().splitlines()[-1])
    assert isinstance(document, dict)
    return exit_code, document


def last_audit_entry(path: Path) -> dict[str, object]:
    """Return the most recent audit line as a decoded object."""

    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines, "no audit entry was written"
    entry = json.loads(lines[-1])
    assert isinstance(entry, dict)
    return entry


def data_of(document: dict[str, object]) -> dict[str, object]:
    """Return the ``data`` payload, failing loudly when absent."""

    payload = document.get("data")
    assert isinstance(payload, dict), f"no data payload: {document}"
    return payload


def error_code(document: dict[str, object]) -> str:
    """Extract ``error.code`` from an envelope, failing loudly when absent."""

    error = document.get("error")
    assert isinstance(error, dict), f"no error payload: {document}"
    code = error.get("code")
    assert isinstance(code, str)
    return code


def test_a_clean_dry_run_reports_clear(configured: Workspace, monkeypatch: MonkeyPatch) -> None:
    exit_code, document = invoke(monkeypatch, "run", "ps aux", "--profile", PROFILE_NAME, "--dry-run")

    payload = data_of(document)
    assert exit_code == 0
    assert payload["dry_run"] is True
    assert payload["verdict"] == GuardVerdict.CLEAR.value
    assert payload["would_block"] is False


def test_a_destructive_dry_run_reports_the_verdict(configured: Workspace, monkeypatch: MonkeyPatch) -> None:
    _, document = invoke(monkeypatch, "run", "rm -rf /", "--profile", PROFILE_NAME, "--dry-run")

    payload = data_of(document)
    assert payload["verdict"] == GuardVerdict.BLOCKED.value
    assert payload["would_block"] is True
    assert payload["danger_categories"] == ["recursive_delete"]


def test_an_unresolvable_dry_run_reports_an_advisory(configured: Workspace, monkeypatch: MonkeyPatch) -> None:
    """\"Could not tell\" stays distinguishable from \"known destructive\"."""

    _, document = invoke(monkeypatch, "run", "rm -rf $TARGET", "--profile", PROFILE_NAME, "--dry-run")

    payload = data_of(document)
    assert payload["verdict"] == GuardVerdict.ADVISORY.value
    assert payload["would_block"] is True


def test_a_destructive_run_is_refused_without_force(configured: Workspace, monkeypatch: MonkeyPatch) -> None:
    exit_code, document = invoke(monkeypatch, "run", "rm -rf /", "--profile", PROFILE_NAME)

    assert exit_code == 1
    assert error_code(document) == "dangerous_command"


def test_a_refused_command_is_recorded_as_blocked(configured: Workspace, monkeypatch: MonkeyPatch) -> None:
    invoke(monkeypatch, "run", "rm -rf /", "--profile", PROFILE_NAME)

    entry = last_audit_entry(configured.audit_path)
    assert entry["status"] == AuditStatus.BLOCKED.value
    assert entry["verdict"] == GuardVerdict.BLOCKED.value
    assert entry["command"] == "rm -rf /"


def test_a_dry_run_is_recorded_separately_from_a_real_run(configured: Workspace, monkeypatch: MonkeyPatch) -> None:
    invoke(monkeypatch, "run", "rm -rf /", "--profile", PROFILE_NAME, "--dry-run")

    assert last_audit_entry(configured.audit_path)["status"] == AuditStatus.DRY_RUN.value


def test_an_empty_command_is_rejected_before_the_guard(configured: Workspace, monkeypatch: MonkeyPatch) -> None:
    exit_code, document = invoke(monkeypatch, "run", "   ", "--profile", PROFILE_NAME)

    assert exit_code == 1
    assert error_code(document) == "invalid_argument"
    assert not configured.audit_path.exists()


def test_a_dry_run_for_an_unknown_profile_sends_nothing(configured: Workspace, monkeypatch: MonkeyPatch) -> None:
    exit_code, document = invoke(monkeypatch, "run", "ps aux", "--profile", "absent", "--dry-run")

    assert exit_code == 1
    assert error_code(document) == "profile_not_found"


def test_a_dry_run_reports_no_captured_streams(configured: Workspace, monkeypatch: MonkeyPatch) -> None:
    """A probe produced no stdout/stderr because nothing ran."""

    _, document = invoke(monkeypatch, "run", "ps aux", "--profile", PROFILE_NAME, "--dry-run")

    payload = data_of(document)
    assert "stdout" not in payload
    assert "stderr" not in payload
