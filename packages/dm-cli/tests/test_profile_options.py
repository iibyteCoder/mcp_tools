"""Click-boundary tests for profile option combinations."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from click.testing import CliRunner

from db_cli_kit.profiles import ProfileName
from dm_cli.adapters.profile_store import JsonProfileStore
from dm_cli.application.profile import ProfileService
from dm_cli.application.runner import CliRuntime
from dm_cli.ports.secret_store import SecretStore
from dm_cli.presentation.click.app import cli

if TYPE_CHECKING:
    from pathlib import Path


@dataclass
class MemorySecretStore(SecretStore):
    values: dict[ProfileName, str] = field(default_factory=dict)

    def get(self, name: ProfileName) -> str | None:
        return self.values.get(name)

    def set(self, name: ProfileName, password: str) -> None:
        self.values[name] = password

    def delete(self, name: ProfileName) -> None:
        self.values.pop(name, None)


def make_runtime(tmp_path: Path) -> tuple[CliRuntime, MemorySecretStore]:
    secrets = MemorySecretStore()
    service = ProfileService(
        JsonProfileStore(tmp_path / "profiles.json", lock_timeout=0.0),
        secrets,
        None,
        working_directory=tmp_path,
    )
    return CliRuntime(profile_service=service), secrets


def invoke(runtime: CliRuntime, *arguments: str, stdin_text: str | None = None) -> tuple[int, dict[str, object]]:
    result = CliRunner().invoke(cli, list(arguments), obj=runtime, input=stdin_text)
    return result.exit_code, json.loads(result.stdout)


def error_code(payload: dict[str, object]) -> str:
    error = payload["error"]
    assert isinstance(error, dict)
    return str(error["code"])


def test_password_stdin_is_read_once_and_never_echoed(tmp_path: Path) -> None:
    runtime, secrets = make_runtime(tmp_path)

    code, payload = invoke(
        runtime,
        "profile",
        "set",
        "dev",
        "--host",
        "db.example",
        "--user",
        "SYSDBA",
        "--password-stdin",
        stdin_text="never-print-this\n",
    )

    assert code == 0
    assert secrets.values[ProfileName(value="dev")] == "never-print-this"
    assert "never-print-this" not in json.dumps(payload)


def test_password_option_combinations_are_rejected(tmp_path: Path) -> None:
    runtime, _ = make_runtime(tmp_path)
    combinations = (
        ("--password", "x", "--password-stdin"),
        ("--password", "x", "--no-password"),
        ("--password-stdin", "--no-password"),
    )

    for combination in combinations:
        code, payload = invoke(
            runtime,
            "profile",
            "set",
            "dev",
            "--host",
            "db.example",
            "--user",
            "SYSDBA",
            *combination,
            stdin_text=None,
        )
        assert code == 2
        assert error_code(payload) == "invalid_argument"


def test_schema_alias_and_clear_combinations_are_rejected(tmp_path: Path) -> None:
    runtime, _ = make_runtime(tmp_path)
    combinations = (
        ("--schema", "APP", "--database", "OTHER"),
        ("--schema", "APP", "--no-schema"),
        ("--database", "APP", "--no-schema"),
        ("--description", "text", "--no-description"),
    )

    for combination in combinations:
        code, payload = invoke(
            runtime,
            "profile",
            "set",
            "dev",
            "--host",
            "db.example",
            "--user",
            "SYSDBA",
            "--no-password",
            *combination,
        )
        assert code == 2
        assert error_code(payload) == "invalid_argument"


def test_zero_query_timeout_is_accepted_but_zero_connect_timeout_is_not(tmp_path: Path) -> None:
    runtime, _ = make_runtime(tmp_path)

    accepted_code, accepted_payload = invoke(
        runtime,
        "profile",
        "set",
        "dev",
        "--host",
        "db.example",
        "--user",
        "SYSDBA",
        "--query-timeout",
        "0",
        "--no-password",
    )
    rejected_code, rejected_payload = invoke(
        runtime,
        "profile",
        "set",
        "prod",
        "--host",
        "db.example",
        "--user",
        "SYSDBA",
        "--connect-timeout",
        "0",
        "--no-password",
    )

    assert accepted_code == 0
    data = accepted_payload["data"]
    assert isinstance(data, dict)
    profile = data["profile"]
    assert isinstance(profile, dict)
    assert profile["query_timeout"] == 0.0
    assert rejected_code == 2
    assert error_code(rejected_payload) == "invalid_argument"
