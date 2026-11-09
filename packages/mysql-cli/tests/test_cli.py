"""Process-level contract tests for ``db-mysql``."""

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
    decoded: object = json.loads(stdout)
    assert isinstance(decoded, dict)
    return cast("JsonObject", decoded)


def as_object(value: JsonValue) -> JsonObject:
    """Narrow one decoded JSON value to an object for contract assertions."""

    assert isinstance(value, dict)
    return value


def as_array(value: JsonValue) -> list[JsonValue]:
    """Narrow one decoded JSON value to an array for contract assertions."""

    assert isinstance(value, list)
    return value


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
    data = as_object(payload["data"])
    assert data["action"] == "read"
    sql = as_object(data["sql"])
    assert sql["statement_type"] == "select"


def test_argument_error_is_json_with_stable_exit_code(cli_environment: dict[str, str]) -> None:
    result = run_cli(cli_environment, "sql", "read", "--sql", "SELECT 1", "--sql-file", "-")

    payload = decode_one_json(result.stdout)
    assert result.returncode == 2
    assert result.stderr == ""
    assert payload["ok"] is False
    error = as_object(payload["error"])
    assert error["code"] == "invalid_argument"
    details = as_array(error["details"])
    assert as_object(details[0])["error_type"] == "mutually_exclusive_inputs"


def test_stdin_sql_file_preserves_source(cli_environment: dict[str, str]) -> None:
    result = run_cli(cli_environment, "sql", "read", "--sql-file", "-", stdin_text="SELECT 1;")

    payload = decode_one_json(result.stdout)
    assert result.returncode == 0
    data = as_object(payload["data"])
    sql = as_object(data["sql"])
    assert sql["source"] == "stdin"
    assert sql["text_length"] == 8
    assert result.stderr == ""


def test_params_object_is_validated_without_echoing_values(cli_environment: dict[str, str], tmp_path: Path) -> None:
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
    data = as_object(payload["data"])
    parameters = as_object(data["parameters"])
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
    error = as_object(payload["error"])
    assert error["code"] == "input_error"
    details = as_array(error["details"])
    assert as_object(details[0])["error_type"] == "invalid_params_type"


def test_invalid_params_json_is_distinguishable(cli_environment: dict[str, str], tmp_path: Path) -> None:
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
    error = as_object(payload["error"])
    details = as_array(error["details"])
    assert as_object(details[0])["error_type"] == "invalid_params_json"
    assert result.stderr == ""


def test_unknown_command_does_not_use_dynamic_fallback(cli_environment: dict[str, str]) -> None:
    result = run_cli(cli_environment, "sql", "query", "--sql", "SELECT 1")

    payload = decode_one_json(result.stdout)
    assert result.returncode == 2
    assert result.stderr == ""
    error = as_object(payload["error"])
    assert error["code"] == "unknown_command"


def test_benchmark_rejects_write_during_local_diagnostics(cli_environment: dict[str, str]) -> None:
    result = run_cli(cli_environment, "sql", "benchmark", "--sql", "UPDATE items SET id = 1")

    payload = decode_one_json(result.stdout)
    assert result.returncode == 2
    assert result.stderr == ""
    error = as_object(payload["error"])
    assert error["code"] == "unsupported_sql"


def test_sql_explain_analyze_is_reported_during_local_diagnostics(
    cli_environment: dict[str, str],
) -> None:
    result = run_cli(cli_environment, "sql", "explain", "--analyze", "--sql", "SELECT 1")

    payload = decode_one_json(result.stdout)
    assert result.returncode == 0
    assert result.stderr == ""
    data = as_object(payload["data"])
    sql = as_object(data["sql"])
    assert sql["statement_type"] == "explain"
    assert sql["read_only"] is True
    assert sql["write"] is False
    assert sql["explain_analyze"] is True
    assert sql["text_length"] == len("EXPLAIN ANALYZE SELECT 1")


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE items SET id = 1",
        "CREATE TABLE items (id INT)",
        "SHOW TABLES",
        "SELECT * FROM items FOR UPDATE",
    ],
)
def test_sql_explain_analyze_rejects_non_select_queries(
    cli_environment: dict[str, str],
    sql: str,
) -> None:
    result = run_cli(cli_environment, "sql", "explain", "--analyze", "--sql", sql)

    payload = decode_one_json(result.stdout)
    assert result.returncode == 2
    assert result.stderr == ""
    error = as_object(payload["error"])
    assert error["code"] == "unsupported_sql"


@pytest.mark.parametrize("sql", ["EXPLAIN SELECT 1", "EXPLAIN ANALYZE SELECT 1"])
def test_sql_explain_analyze_rejects_existing_explain(
    cli_environment: dict[str, str],
    sql: str,
) -> None:
    result = run_cli(cli_environment, "sql", "explain", "--analyze", "--sql", sql)

    payload = decode_one_json(result.stdout)
    assert result.returncode == 2
    assert result.stderr == ""
    error = as_object(payload["error"])
    assert error["code"] == "invalid_argument"


def test_sql_explain_help_lists_analyze(cli_environment: dict[str, str]) -> None:
    result = run_cli(cli_environment, "sql", "explain", "--help")

    assert result.returncode == 0
    assert result.stderr == ""
    assert "--analyze" in result.stdout


@pytest.mark.parametrize(
    ("command", "sql"),
    [
        ("read", "SELECT * FROM items FOR UPDATE"),
        ("benchmark", "SELECT GET_LOCK('items', 1)"),
    ],
)
def test_read_only_commands_reject_locking_side_effects(
    cli_environment: dict[str, str], command: str, sql: str
) -> None:
    result = run_cli(cli_environment, "sql", command, "--sql", sql)

    payload = decode_one_json(result.stdout)
    assert result.returncode == 2
    assert result.stderr == ""
    error = as_object(payload["error"])
    assert error["code"] == "unsupported_sql"


@pytest.mark.parametrize(
    ("left_sql", "right_sql", "expected_code"),
    [
        ("UPDATE items SET id = 1", "SELECT 1", "unsupported_sql"),
        ("SELECT 1", "DELETE FROM items", "unsupported_sql"),
        ("SELECT (", "SELECT 1", "invalid_sql"),
        ("SELECT 1", "SELECT (", "invalid_sql"),
    ],
)
def test_compare_validates_both_sql_inputs_during_local_diagnostics(
    cli_environment: dict[str, str],
    left_sql: str,
    right_sql: str,
    expected_code: str,
) -> None:
    result = run_cli(
        cli_environment,
        "sql",
        "compare",
        "--left-sql",
        left_sql,
        "--right-sql",
        right_sql,
    )

    payload = decode_one_json(result.stdout)
    assert result.returncode == 2
    assert result.stderr == ""
    error = as_object(payload["error"])
    assert error["code"] == expected_code


def test_missing_file_is_typed(cli_environment: dict[str, str], tmp_path: Path) -> None:
    result = run_cli(cli_environment, "sql", "read", "--sql-file", str(tmp_path / "missing.sql"))

    payload = decode_one_json(result.stdout)
    assert result.returncode == 3
    assert result.stderr == ""
    error = as_object(payload["error"])
    details = as_array(error["details"])
    assert as_object(details[0])["error_type"] == "file_not_found"


def test_real_profile_read_only_commands_are_process_level(cli_environment: dict[str, str]) -> None:
    profile_name = os.environ.get("DB_MYSQL_REAL_PROFILE")
    if not profile_name:
        pytest.skip("set DB_MYSQL_REAL_PROFILE to run the real read-only profile E2E")

    commands = (
        ("profile list", ("profile", "list")),
        ("profile show", ("profile", "show", profile_name)),
        ("profile validate", ("profile", "validate", profile_name)),
        ("sql read", ("--profile", profile_name, "sql", "read", "--sql", "SELECT 1")),
        ("server inspect", ("--profile", profile_name, "server", "inspect")),
        ("schema databases", ("--profile", profile_name, "schema", "databases")),
        ("sql explain", ("--profile", profile_name, "sql", "explain", "--sql", "EXPLAIN SELECT 1")),
    )

    for label, arguments in commands:
        result = run_cli(cli_environment, "--json", *arguments)
        payload = decode_one_json(result.stdout)
        assert result.returncode == 0, f"{label}: {payload}"
        assert payload["ok"] is True, f"{label}: {payload}"
        assert '"password":' not in result.stdout
        data = as_object(payload["data"])
        if label == "profile list":
            profiles = as_array(data["profiles"])
            selected = next(
                item_object for item in profiles if (item_object := as_object(item))["name"] == profile_name
            )
            assert "description" in selected
            assert "password" not in selected
        elif label == "profile show":
            profile = as_object(data["profile"])
            assert "description" in profile
            assert "password" not in profile


def test_real_profile_server_processes_hides_info_by_default(cli_environment: dict[str, str]) -> None:
    profile_name = os.environ.get("DB_MYSQL_REAL_PROFILE")
    if not profile_name:
        pytest.skip("set DB_MYSQL_REAL_PROFILE to run the real server processes E2E")

    expected_columns = ["id", "user", "host", "database", "command", "time_seconds", "state", "info"]
    default_result = run_cli(cli_environment, "--json", "--profile", profile_name, "server", "processes")
    default_payload = decode_one_json(default_result.stdout)
    assert default_result.returncode == 0, default_payload
    assert default_result.stderr == ""
    assert default_payload["ok"] is True
    default_data = as_object(default_payload["data"])
    assert default_data["command_group"] == "server"
    assert default_data["action"] == "processes"
    default_query = as_object(as_object(default_data["result"])["query"])
    assert [as_object(column)["name"] for column in as_array(default_query["columns"])] == expected_columns
    default_rows = [as_array(as_object(row)["values"]) for row in as_array(default_query["rows"])]
    assert default_rows
    assert [row[0] for row in default_rows] == sorted(row[0] for row in default_rows)
    assert all(row[7] is None for row in default_rows)

    sql_result = run_cli(
        cli_environment,
        "--json",
        "--profile",
        profile_name,
        "server",
        "processes",
        "--include-sql",
    )
    sql_payload = decode_one_json(sql_result.stdout)
    assert sql_result.returncode == 0, sql_payload
    assert sql_result.stderr == ""
    assert sql_payload["ok"] is True
    sql_query = as_object(as_object(as_object(sql_payload["data"])["result"])["query"])
    assert [as_object(column)["name"] for column in as_array(sql_query["columns"])] == expected_columns
    sql_rows = [as_array(as_object(row)["values"]) for row in as_array(sql_query["rows"])]
    assert sql_rows
    assert [row[0] for row in sql_rows] == sorted(row[0] for row in sql_rows)
    assert any(row[7] is not None for row in sql_rows)
