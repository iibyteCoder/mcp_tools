"""Call-level tests for the public process entry point."""

from __future__ import annotations

import json

import mysql_cli.cli as cli_module
from mysql_cli.cli import main
from mysql_cli.profile_store import JsonProfileStore


def test_main_parses_non_sql_command_without_database_access(capsys: object) -> None:
    result = main(["profile", "list"])

    assert result == 0
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["ok"] is True
    assert payload["data"]["command_group"] == "profile"
    assert payload["data"]["action"] == "list"


def test_main_rejects_read_policy_for_write_sql(capsys: object) -> None:
    result = main(["sql", "read", "--sql", "UPDATE users SET name = 'x'"])

    assert result == 2
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "unsupported_sql"
    assert payload["error"]["details"][0]["error_type"] == "policy_violation"


def test_profile_list_uses_cli_lock_wait_policy(monkeypatch: object, capsys: object) -> None:
    observed: dict[str, float] = {}
    original_store = JsonProfileStore

    class ObservedStore(original_store):
        def __init__(self, *args: object, **kwargs: object) -> None:
            lock_timeout = kwargs.get("lock_timeout")
            if isinstance(lock_timeout, float):
                observed["lock_timeout"] = lock_timeout
            super().__init__(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(cli_module, "JsonProfileStore", ObservedStore)
    assert main(["profile", "list"]) == 0
    capsys.readouterr()

    assert observed["lock_timeout"] == JsonProfileStore.CLI_LOCK_TIMEOUT_SECONDS
