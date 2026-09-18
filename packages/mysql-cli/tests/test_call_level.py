"""Call-level tests for the public process entry point."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import mysql_cli.cli as cli_module
from mysql_cli.cli import main
from mysql_cli.profile_store import JsonProfileStore

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


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

    monkeypatch.setattr(cli_module, "JsonProfileStore", ObservedStore)
    assert main(["profile", "list"]) == 0
    capsys.readouterr()

    assert observed["lock_timeout"] == JsonProfileStore.CLI_LOCK_TIMEOUT_SECONDS
