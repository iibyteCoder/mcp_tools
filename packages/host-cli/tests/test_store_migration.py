"""The registry must keep carrying profile data across format changes.

Two migrations are represented here: the three gate settings added after registries
were already on disk, and the audit ``verdict`` field added after audit logs
existed. In both cases the older file must still load -- an upgrade that orphaned
existing data would be worse than not adding the feature.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from db_cli_kit.profiles import ProfileName
from host_cli.domain.enums import AuditStatus, GuardVerdict
from host_cli.domain.errors import HostCliError
from host_cli.domain.models import DEFAULT_MAX_COMMANDS_PER_MINUTE, ProfileSettings
from host_cli.infrastructure.profile_store import ProfileStore

if TYPE_CHECKING:
    from pathlib import Path

NAME = ProfileName(value="dev")

LEGACY_SETTINGS = {
    "host": "example",
    "user": "operator",
    "port": 22,
    "description": None,
    "command_timeout": 60.0,
}
"""Settings exactly as they were written before the gate fields existed."""


def write_registry(path: Path, settings: object) -> None:
    """Write a registry document with the given settings block."""

    path.write_text(
        json.dumps({"profiles": [{"name": NAME.value, "settings": settings}]}),
        encoding="utf-8",
    )


def settings_of(path: Path) -> ProfileSettings:
    """Return the stored settings for the single profile in ``path``."""

    record = ProfileStore(path).read().find(NAME)
    assert record is not None, "the registry did not yield the stored profile"
    return record.settings


def test_a_legacy_registry_still_loads(tmp_path: Path) -> None:
    """A profile written by an earlier version must not become unreadable."""

    path = tmp_path / "profiles.json"
    write_registry(path, LEGACY_SETTINGS)

    settings = settings_of(path)

    assert settings.host == "example"


def test_a_legacy_registry_defaults_to_permissive_gates(tmp_path: Path) -> None:
    """The missing keys mean "no gate was configured", not "enable every gate".

    Defaulting to read-only would make an upgrade silently break every existing
    profile, which is a worse outcome than keeping the previous behaviour.
    """

    path = tmp_path / "profiles.json"
    write_registry(path, LEGACY_SETTINGS)

    settings = settings_of(path)

    assert settings.read_only is False
    assert settings.requires_approval is False
    assert settings.max_commands_per_minute == DEFAULT_MAX_COMMANDS_PER_MINUTE


def test_the_gate_settings_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "profiles.json"
    stored = {**LEGACY_SETTINGS, "read_only": True, "requires_approval": True, "max_commands_per_minute": 7}
    write_registry(path, stored)

    settings = settings_of(path)

    assert settings.read_only is True
    assert settings.requires_approval is True
    assert settings.max_commands_per_minute == 7


def test_a_non_boolean_flag_is_rejected(tmp_path: Path) -> None:
    """A malformed flag must fail loudly rather than be coerced to ``True``."""

    path = tmp_path / "profiles.json"
    write_registry(path, {**LEGACY_SETTINGS, "read_only": "yes"})

    with pytest.raises(HostCliError):
        ProfileStore(path).read()


def test_a_negative_rate_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "profiles.json"
    write_registry(path, {**LEGACY_SETTINGS, "max_commands_per_minute": -1})

    with pytest.raises(HostCliError):
        ProfileStore(path).read()


def test_an_unknown_settings_key_is_rejected(tmp_path: Path) -> None:
    """Unknown keys stay an error: silently ignoring them hides a typo in a config."""

    path = tmp_path / "profiles.json"
    write_registry(path, {**LEGACY_SETTINGS, "readonly": True})

    with pytest.raises(HostCliError):
        ProfileStore(path).read()


def test_a_missing_required_key_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "profiles.json"
    incomplete = {key: value for key, value in LEGACY_SETTINGS.items() if key != "port"}
    write_registry(path, incomplete)

    with pytest.raises(HostCliError):
        ProfileStore(path).read()


def test_an_audit_entry_without_a_verdict_still_reads(tmp_path: Path) -> None:
    """The audit field was added after entries existed; old ones must remain usable."""

    from host_cli.application.probe import read_audit

    path = tmp_path / "audit.jsonl"
    path.write_text(
        json.dumps(
            {
                "timestamp": "2026-11-20T09:00:00+00:00",
                "profile": "dev",
                "host": "example",
                "user": "operator",
                "command": "rm -rf /",
                "status": "blocked",
                "outcome": None,
                "remote_exit_code": None,
                "remote_state": None,
                "duration_ms": 0,
                "stdout_bytes": 0,
                "stderr_bytes": 0,
                "truncated": False,
                "forced": False,
                "danger_categories": ["recursive_delete"],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    entries = read_audit(path)

    assert len(entries) == 1
    assert entries[0].status is AuditStatus.BLOCKED
    assert entries[0].verdict is GuardVerdict.BLOCKED
