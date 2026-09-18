"""Process-level contract tests for ``db-mysql``."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import TypeAlias

import pytest

JsonObject: TypeAlias = dict[str, object]


@pytest.fixture
def cli_environment() -> dict[str, str]:
    """Return an environment that exposes both new package source trees."""

    repository_root = Path(__file__).resolve().parents[3]
    source_paths = (
        repository_root / "packages" / "mysql-cli" / "src",
        repository_root / "libs" / "mysql-client" / "src",
    )
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(str(path) for path in source_paths)
    return environment


def run_cli(
    cli_environment: dict[str, str],
    *arguments: str,
    stdin_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the package in a fresh process."""

    return subprocess.run(
        [sys.executable, "-m", "mysql_cli", *arguments],
        capture_output=True,
        check=False,
        env=cli_environment,
        input=stdin_text,
        text=True,
    )


def decode_one_json(stdout: str) -> JsonObject:
    """Decode exactly one JSON document terminated by one newline."""

    assert stdout.endswith("\n")
    assert stdout.count("\n") == 1
    decoded = json.loads(stdout)
    assert isinstance(decoded, dict)
    return decoded


def test_help_is_readable_and_quiet(cli_environment: dict[str, str]) -> None:
    result = run_cli(cli_environment, "help")

    assert result.returncode == 0
    assert "profile" in result.stdout
    assert "sql" in result.stdout
    assert result.stderr == ""


def test_version_is_fast_and_quiet(cli_environment: dict[str, str]) -> None:
    result = run_cli(cli_environment, "--version")

    assert result.returncode == 0
    assert result.stdout == "db-mysql 0.1.0\n"
    assert result.stderr == ""


def test_success_is_one_json_document(cli_environment: dict[str, str]) -> None:
    result = run_cli(cli_environment, "sql", "read", "--sql", "SELECT 1")

    payload = decode_one_json(result.stdout)
    assert result.returncode == 0
    assert result.stderr == ""
    assert payload["ok"] is True
    data = payload["data"]
    assert isinstance(data, dict)
    assert data["action"] == "read"
    sql = data["sql"]
    assert isinstance(sql, dict)
    assert sql["statement_type"] == "select"


def test_argument_error_is_json_with_stable_exit_code(cli_environment: dict[str, str]) -> None:
    result = run_cli(cli_environment, "sql", "read", "--sql", "SELECT 1", "--sql-file", "-")

    payload = decode_one_json(result.stdout)
    assert result.returncode == 2
    assert result.stderr == ""
    assert payload["ok"] is False
    error = payload["error"]
    assert isinstance(error, dict)
    assert error["code"] == "invalid_argument"
    details = error["details"]
    assert isinstance(details, list)
    assert details[0]["error_type"] == "mutually_exclusive_inputs"


def test_stdin_sql_file_preserves_source(cli_environment: dict[str, str]) -> None:
    result = run_cli(cli_environment, "sql", "read", "--sql-file", "-", stdin_text="SELECT 1;")

    payload = decode_one_json(result.stdout)
    assert result.returncode == 0
    data = payload["data"]
    assert isinstance(data, dict)
    sql = data["sql"]
    assert isinstance(sql, dict)
    assert sql["source"] == "stdin"
    assert sql["text_length"] == 8
    assert result.stderr == ""


def test_params_object_is_validated_without_echoing_values(
    cli_environment: dict[str, str], tmp_path: Path
) -> None:
    params_file = tmp_path / "params.json"
    params_file.write_text('{"user":"alice","secret":"do-not-echo"}', encoding="utf-8")

    result = run_cli(
        cli_environment,
        "sql",
        "read",
        "--sql",
        "SELECT %s",
        "--params-file",
        str(params_file),
    )

    payload = decode_one_json(result.stdout)
    assert result.returncode == 0
    assert "do-not-echo" not in result.stdout
    data = payload["data"]
    assert isinstance(data, dict)
    parameters = data["parameters"]
    assert isinstance(parameters, dict)
    assert parameters["kind"] == "object"
    assert parameters["count"] == 2
    assert result.stderr == ""


@pytest.mark.parametrize("params_text", ["null", '"scalar"', "123"])
def test_params_top_level_must_be_object_or_array(
    cli_environment: dict[str, str], tmp_path: Path, params_text: str
) -> None:
    params_file = tmp_path / "params.json"
    params_file.write_text(params_text, encoding="utf-8")

    result = run_cli(
        cli_environment,
        "sql",
        "read",
        "--sql",
        "SELECT 1",
        "--params-file",
        str(params_file),
    )

    payload = decode_one_json(result.stdout)
    assert result.returncode == 3
    assert result.stderr == ""
    error = payload["error"]
    assert isinstance(error, dict)
    assert error["code"] == "input_error"
    details = error["details"]
    assert isinstance(details, list)
    assert details[0]["error_type"] == "invalid_params_type"


def test_invalid_params_json_is_distinguishable(
    cli_environment: dict[str, str], tmp_path: Path
) -> None:
    params_file = tmp_path / "params.json"
    params_file.write_text("{not-json}", encoding="utf-8")

    result = run_cli(
        cli_environment,
        "sql",
        "read",
        "--sql",
        "SELECT 1",
        "--params-file",
        str(params_file),
    )

    payload = decode_one_json(result.stdout)
    assert result.returncode == 3
    error = payload["error"]
    assert isinstance(error, dict)
    details = error["details"]
    assert isinstance(details, list)
    assert details[0]["error_type"] == "invalid_params_json"
    assert result.stderr == ""


def test_unknown_command_does_not_use_dynamic_fallback(cli_environment: dict[str, str]) -> None:
    result = run_cli(cli_environment, "sql", "query", "--sql", "SELECT 1")

    payload = decode_one_json(result.stdout)
    assert result.returncode == 2
    assert result.stderr == ""
    error = payload["error"]
    assert isinstance(error, dict)
    assert error["code"] == "unknown_command"


def test_missing_file_is_typed(cli_environment: dict[str, str], tmp_path: Path) -> None:
    result = run_cli(cli_environment, "sql", "read", "--sql-file", str(tmp_path / "missing.sql"))

    payload = decode_one_json(result.stdout)
    assert result.returncode == 3
    assert result.stderr == ""
    error = payload["error"]
    assert isinstance(error, dict)
    details = error["details"]
    assert isinstance(details, list)
    assert details[0]["error_type"] == "file_not_found"
