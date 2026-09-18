"""Call-level tests for the public process entry point."""

from __future__ import annotations

import json

from mysql_command.cli import main


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
