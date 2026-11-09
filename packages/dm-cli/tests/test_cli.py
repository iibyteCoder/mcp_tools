"""Process-level contract tests for ``db-dm``."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

if TYPE_CHECKING:
    from db_cli_kit.json_codec import JsonObject, JsonValue

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SOURCE_PATHS = (
    REPOSITORY_ROOT / "packages" / "dm-cli" / "src",
    REPOSITORY_ROOT / "libs" / "dm-client" / "src",
    REPOSITORY_ROOT / "libs" / "db-cli-kit" / "src",
)


@pytest.fixture
def cli_environment(tmp_path: Path) -> dict[str, str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(str(path) for path in SOURCE_PATHS)
    environment["DB_DM_CONFIG_DIR"] = str(tmp_path / "config")
    return environment


def run_cli(
    cli_environment: dict[str, str],
    *arguments: str,
    stdin_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "dm_cli", *arguments],
        capture_output=True,
        check=False,
        env=cli_environment,
        input=stdin_text,
        text=True,
    )


def decode_one_json(stdout: str) -> JsonObject:
    assert stdout.endswith("\n")
    assert stdout.count("\n") == 1
    decoded: object = json.loads(stdout)
    assert isinstance(decoded, dict)
    return cast("JsonObject", decoded)


def as_object(value: JsonValue) -> JsonObject:
    assert isinstance(value, dict)
    return value


def as_array(value: JsonValue) -> list[JsonValue]:
    assert isinstance(value, list)
    return value


def test_help_is_readable_and_quiet(cli_environment: dict[str, str]) -> None:
    result = run_cli(cli_environment, "help")

    assert result.returncode == 0
    assert "profile" in result.stdout
    assert "server" in result.stdout
    assert "schema" in result.stdout
    assert result.stderr == ""


def test_version_is_plain_and_quiet(cli_environment: dict[str, str]) -> None:
    result = run_cli(cli_environment, "--version")

    assert result.returncode == 0
    assert result.stdout == "db-dm 0.1.0\n"
    assert result.stderr == ""


def test_profile_list_is_one_json_document(cli_environment: dict[str, str]) -> None:
    result = run_cli(cli_environment, "profile", "list")

    payload = decode_one_json(result.stdout)
    assert result.returncode == 0
    assert result.stderr == ""
    assert payload["ok"] is True
    data = as_object(payload["data"])
    assert data["status"] == "completed"
    assert data["command_group"] == "profile"
    assert data["action"] == "list"
    assert data["profiles"] == []


def test_profile_set_and_show_round_trip_without_password(
    cli_environment: dict[str, str], tmp_path: Path
) -> None:
    created = run_cli(
        cli_environment,
        "profile",
        "set",
        "dev",
        "--host",
        "127.0.0.1",
        "--user",
        "SYSDBA",
        "--schema",
        "APP",
        "--no-password",
    )

    payload = decode_one_json(created.stdout)
    assert created.returncode == 0
    assert created.stderr == ""
    profile = as_object(as_object(payload["data"])["profile"])
    assert profile == {
        "name": "dev",
        "description": None,
        "host": "127.0.0.1",
        "port": 5236,
        "user": "SYSDBA",
        "schema": "APP",
        "connect_timeout": 5.0,
        "query_timeout": 0.0,
        "password_present": False,
    }
    assert '"password":' not in created.stdout
    registry_path = tmp_path / "config" / "profiles.json"
    registry = registry_path.read_text(encoding="utf-8")
    assert '"schema": "db-dm.profile-registry"' in registry
    assert '"password":' not in registry

    shown = run_cli(cli_environment, "profile", "show", "dev")
    shown_payload = decode_one_json(shown.stdout)
    assert shown.returncode == 0
    assert shown.stderr == ""
    assert as_object(as_object(shown_payload["data"])["profile"])["name"] == "dev"


def test_profile_validate_reports_a_missing_secret(cli_environment: dict[str, str]) -> None:
    run_cli(
        cli_environment,
        "profile",
        "set",
        "dev",
        "--host",
        "127.0.0.1",
        "--user",
        "SYSDBA",
        "--no-password",
    )

    result = run_cli(cli_environment, "profile", "validate", "dev")

    payload = decode_one_json(result.stdout)
    assert result.returncode == 4
    assert result.stderr == ""
    assert payload["ok"] is False
    error = as_object(payload["error"])
    assert error["code"] == "secret_store_error"
    details = as_array(error["details"])
    assert as_object(details[0])["error_type"] == "secret_store_error"


def test_duplicate_rename_is_a_profile_conflict(cli_environment: dict[str, str]) -> None:
    for name in ("dev", "prod"):
        run_cli(
            cli_environment,
            "profile",
            "set",
            name,
            "--host",
            "127.0.0.1",
            "--user",
            "SYSDBA",
            "--no-password",
        )

    result = run_cli(cli_environment, "profile", "rename", "dev", "prod")

    payload = decode_one_json(result.stdout)
    assert result.returncode == 4
    assert result.stderr == ""
    error = as_object(payload["error"])
    assert error["code"] == "profile_conflict"


def test_unknown_command_is_json_and_quiet(cli_environment: dict[str, str]) -> None:
    result = run_cli(cli_environment, "profile", "nope")

    payload = decode_one_json(result.stdout)
    assert result.returncode == 2
    assert result.stderr == ""
    assert payload["ok"] is False
    assert as_object(payload["error"])["code"] == "unknown_command"


def test_bad_option_is_json_and_quiet(cli_environment: dict[str, str]) -> None:
    result = run_cli(cli_environment, "profile", "list", "--bogus")

    payload = decode_one_json(result.stdout)
    assert result.returncode == 2
    assert result.stderr == ""
    error = as_object(payload["error"])
    assert error["code"] == "invalid_argument"
    details = as_array(error["details"])
    assert as_object(details[0])["error_type"] == "argument_syntax"


def test_schema_and_database_aliases_are_mutually_exclusive(cli_environment: dict[str, str]) -> None:
    result = run_cli(
        cli_environment,
        "profile",
        "set",
        "dev",
        "--host",
        "127.0.0.1",
        "--user",
        "SYSDBA",
        "--schema",
        "APP",
        "--database",
        "OTHER",
        "--no-password",
    )

    payload = decode_one_json(result.stdout)
    assert result.returncode == 2
    assert result.stderr == ""
    error = as_object(payload["error"])
    assert error["code"] == "invalid_argument"
    details = as_array(error["details"])
    assert as_object(details[0])["error_type"] == "mutually_exclusive_inputs"
