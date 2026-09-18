"""Call-level tests for the public process entry point."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import mysql_cli.composition as composition
from mysql_cli.adapters.profile_store import JsonProfileStore
from mysql_cli.ports.secret_store import SecretStore
from mysql_cli.presentation.click.app import main

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

    from mysql_cli.domain.profile import ProfileName


def test_main_parses_non_sql_command_without_database_access(capsys: pytest.CaptureFixture[str]) -> None:
    result = main(["profile", "list"])

    assert result == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["ok"] is True
    assert payload["data"]["command_group"] == "profile"
    assert payload["data"]["action"] == "list"


def test_main_rejects_read_policy_for_write_sql(capsys: pytest.CaptureFixture[str]) -> None:
    result = main(["sql", "read", "--sql", "UPDATE users SET name = 'x'"])

    assert result == 2
    captured = capsys.readouterr()
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "unsupported_sql"
    assert payload["error"]["details"][0]["error_type"] == "policy_violation"


def test_profile_list_uses_cli_lock_wait_policy(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    observed: dict[str, float] = {}

    class ObservedStore(JsonProfileStore):
        def __init__(self, path: Path | None = None, *, lock_timeout: float = 0.0) -> None:
            observed["lock_timeout"] = lock_timeout
            super().__init__(path, lock_timeout=lock_timeout)

    monkeypatch.setattr(composition, "JsonProfileStore", ObservedStore)
    assert main(["profile", "list"]) == 0
    capsys.readouterr()

    assert observed["lock_timeout"] == JsonProfileStore.CLI_LOCK_TIMEOUT_SECONDS


def test_profile_description_set_clear_and_json_output(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    class MemorySecrets(SecretStore):
        def get(self, name: ProfileName) -> str | None:
            del name
            return None

        def set(self, name: ProfileName, password: str) -> None:
            del name, password

        def delete(self, name: ProfileName) -> None:
            del name

    class TempStore(JsonProfileStore):
        def __init__(self, path: Path | None = None, *, lock_timeout: float = 0.0) -> None:
            del path
            super().__init__(tmp_path / "profiles.json", lock_timeout=lock_timeout)

    monkeypatch.setattr(composition, "JsonProfileStore", TempStore)
    monkeypatch.setattr(composition, "KeyringSecretStore", MemorySecrets)

    assert (
        main(
            [
                "profile",
                "set",
                "dev",
                "--host",
                "db.example",
                "--user",
                "alice",
                "--description",
                "read-only test database",
            ]
        )
        == 0
    )
    created = json.loads(capsys.readouterr().out)
    assert created["data"]["profile"]["description"] == "read-only test database"

    assert main(["profile", "show", "dev"]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["data"]["profile"]["description"] == "read-only test database"

    assert main(["profile", "set", "dev", "--no-description"]) == 0
    cleared = json.loads(capsys.readouterr().out)
    assert cleared["data"]["profile"]["description"] is None

    assert main(["profile", "list"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert listed["data"]["profiles"][0]["description"] is None
