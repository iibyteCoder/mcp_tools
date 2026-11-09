"""Process-level contract tests for ``db-dm sql`` commands."""

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


def error_of(payload: JsonObject) -> JsonObject:
    assert payload["ok"] is False
    return as_object(payload["error"])


def test_help_lists_the_sql_command_group(cli_environment: dict[str, str]) -> None:
    result = run_cli(cli_environment, "help")

    assert result.returncode == 0
    assert "sql" in result.stdout
    assert result.stderr == ""


def test_read_without_a_profile_reports_local_diagnostics(cli_environment: dict[str, str]) -> None:
    result = run_cli(cli_environment, "sql", "read", "--sql", "SELECT 1")

    payload = decode_one_json(result.stdout)
    assert result.returncode == 0
    assert result.stderr == ""
    assert payload["ok"] is True
    data = as_object(payload["data"])
    assert data["status"] == "parsed"
    assert data["command_group"] == "sql"
    assert data["action"] == "read"
    assert data["parameters"] is None
    sql = as_object(data["sql"])
    assert sql["statement_type"] == "select"
    assert sql["read_only"] is True
    assert sql["write"] is False
    assert sql["requires_explicit_transaction"] is False
    assert sql["explain_analyze"] is False
    assert sql["text_length"] == len("SELECT 1")
    assert sql["source"] == "inline"
    meta = as_object(payload["meta"])
    assert meta["input_source"] == "inline"


def test_write_without_a_profile_reports_local_diagnostics(cli_environment: dict[str, str]) -> None:
    result = run_cli(cli_environment, "sql", "write", "--sql", "UPDATE t SET x = 1")

    payload = decode_one_json(result.stdout)
    assert result.returncode == 0
    assert result.stderr == ""
    data = as_object(payload["data"])
    assert data["action"] == "write"
    sql = as_object(data["sql"])
    assert sql["statement_type"] == "update"
    assert sql["read_only"] is False
    assert sql["write"] is True
    assert sql["requires_explicit_transaction"] is True


def test_explain_without_a_profile_reports_local_diagnostics(cli_environment: dict[str, str]) -> None:
    result = run_cli(cli_environment, "sql", "explain", "--sql", "SELECT 1 AS N FROM DUAL")

    payload = decode_one_json(result.stdout)
    assert result.returncode == 0
    assert result.stderr == ""
    data = as_object(payload["data"])
    assert data["status"] == "parsed"
    assert data["action"] == "explain"
    sql = as_object(data["sql"])
    assert sql["statement_type"] == "select"
    assert sql["read_only"] is True
    assert sql["explain_analyze"] is False


def test_explain_diagnostic_accepts_a_leading_explain_token(cli_environment: dict[str, str]) -> None:
    result = run_cli(cli_environment, "sql", "explain", "--sql", "EXPLAIN SELECT 1 AS N FROM DUAL")

    payload = decode_one_json(result.stdout)
    assert result.returncode == 0
    assert result.stderr == ""
    sql = as_object(as_object(payload["data"])["sql"])
    assert sql["statement_type"] == "explain"
    assert sql["explain_analyze"] is False


def test_explain_analyze_is_rejected_as_unsupported_sql(cli_environment: dict[str, str]) -> None:
    result = run_cli(cli_environment, "sql", "explain", "--sql", "EXPLAIN ANALYZE SELECT 1 FROM DUAL")

    payload = decode_one_json(result.stdout)
    assert result.returncode == 2
    assert result.stderr == ""
    error = error_of(payload)
    assert error["code"] == "unsupported_sql"
    details = as_array(error["details"])
    assert as_object(details[0])["error_type"] == "policy_violation"


def test_explain_does_not_accept_params_file(cli_environment: dict[str, str], tmp_path: Path) -> None:
    params_file = tmp_path / "params.json"
    params_file.write_text("[1]", encoding="utf-8")

    result = run_cli(cli_environment, "sql", "explain", "--sql", "SELECT 1", "--params-file", str(params_file))

    payload = decode_one_json(result.stdout)
    assert result.returncode == 2
    assert result.stderr == ""
    error = error_of(payload)
    assert error["code"] == "invalid_argument"
    details = as_array(error["details"])
    assert as_object(details[0])["error_type"] == "argument_syntax"


def test_explain_actual_without_a_profile_reports_local_diagnostics(cli_environment: dict[str, str]) -> None:
    result = run_cli(cli_environment, "sql", "explain", "--actual", "--sql", "SELECT 1")

    payload = decode_one_json(result.stdout)
    assert result.returncode == 0
    assert result.stderr == ""
    data = as_object(payload["data"])
    assert data["status"] == "parsed"
    assert data["action"] == "explain"
    sql = as_object(data["sql"])
    assert sql["statement_type"] == "select"
    assert sql["read_only"] is True
    assert sql["write"] is False
    assert sql["requires_explicit_transaction"] is False
    assert sql["explain_analyze"] is False
    assert sql["text_length"] == len("SELECT 1")


def test_explain_actual_strips_a_leading_explain_token(cli_environment: dict[str, str]) -> None:
    result = run_cli(cli_environment, "sql", "explain", "--actual", "--sql", "EXPLAIN SELECT 1")

    payload = decode_one_json(result.stdout)
    assert result.returncode == 0
    assert result.stderr == ""
    sql = as_object(as_object(payload["data"])["sql"])
    assert sql["statement_type"] == "select"
    assert sql["explain_analyze"] is False
    assert sql["text_length"] == len("SELECT 1")


def test_explain_actual_rejects_a_write_statement(cli_environment: dict[str, str]) -> None:
    result = run_cli(cli_environment, "sql", "explain", "--actual", "--sql", "UPDATE t SET x = 1")

    payload = decode_one_json(result.stdout)
    assert result.returncode == 2
    assert result.stderr == ""
    error = error_of(payload)
    assert error["code"] == "unsupported_sql"
    details = as_array(error["details"])
    assert as_object(details[0])["error_type"] == "policy_violation"


def test_explain_actual_rejects_explain_analyze(cli_environment: dict[str, str]) -> None:
    result = run_cli(
        cli_environment,
        "sql",
        "explain",
        "--actual",
        "--sql",
        "EXPLAIN ANALYZE SELECT 1 FROM DUAL",
    )

    payload = decode_one_json(result.stdout)
    assert result.returncode == 2
    assert result.stderr == ""
    error = error_of(payload)
    assert error["code"] == "unsupported_sql"
    details = as_array(error["details"])
    assert as_object(details[0])["error_type"] == "policy_violation"


def test_explain_actual_does_not_accept_params_file(
    cli_environment: dict[str, str], tmp_path: Path
) -> None:
    params_file = tmp_path / "params.json"
    params_file.write_text("[1]", encoding="utf-8")

    result = run_cli(
        cli_environment,
        "sql",
        "explain",
        "--actual",
        "--sql",
        "SELECT 1",
        "--params-file",
        str(params_file),
    )

    payload = decode_one_json(result.stdout)
    assert result.returncode == 2
    assert result.stderr == ""
    error = error_of(payload)
    assert error["code"] == "invalid_argument"
    details = as_array(error["details"])
    assert as_object(details[0])["error_type"] == "argument_syntax"


def test_explain_help_lists_the_actual_flag(cli_environment: dict[str, str]) -> None:
    result = run_cli(cli_environment, "sql", "explain", "--help")

    assert result.returncode == 0
    assert result.stderr == ""
    assert "--actual" in result.stdout
    assert "AUTOTRACE TRACEONLY" in result.stdout


def test_read_rejects_a_write_statement(cli_environment: dict[str, str]) -> None:
    result = run_cli(cli_environment, "sql", "read", "--sql", "UPDATE t SET x = 1")

    payload = decode_one_json(result.stdout)
    assert result.returncode == 2
    assert result.stderr == ""
    error = error_of(payload)
    assert error["code"] == "unsupported_sql"
    details = as_array(error["details"])
    assert as_object(details[0])["error_type"] == "policy_violation"


def test_empty_sql_is_invalid_sql(cli_environment: dict[str, str]) -> None:
    result = run_cli(cli_environment, "sql", "read", "--sql", "")

    payload = decode_one_json(result.stdout)
    assert result.returncode == 2
    assert result.stderr == ""
    error = error_of(payload)
    assert error["code"] == "invalid_sql"
    details = as_array(error["details"])
    assert as_object(details[0])["error_type"] == "sql_parse"


def test_malformed_sql_is_invalid_sql(cli_environment: dict[str, str]) -> None:
    result = run_cli(cli_environment, "sql", "read", "--sql", "SELECT 'unterminated")

    payload = decode_one_json(result.stdout)
    assert result.returncode == 2
    assert result.stderr == ""
    error = error_of(payload)
    assert error["code"] == "invalid_sql"
    details = as_array(error["details"])
    assert as_object(details[0])["error_type"] == "sql_parse"


def test_sql_option_and_sql_file_are_mutually_exclusive(
    cli_environment: dict[str, str], tmp_path: Path
) -> None:
    sql_file = tmp_path / "query.sql"
    sql_file.write_text("SELECT 1", encoding="utf-8")

    result = run_cli(cli_environment, "sql", "read", "--sql", "SELECT 1", "--sql-file", str(sql_file))

    payload = decode_one_json(result.stdout)
    assert result.returncode == 2
    assert result.stderr == ""
    error = error_of(payload)
    assert error["code"] == "invalid_argument"
    details = as_array(error["details"])
    assert as_object(details[0])["error_type"] == "mutually_exclusive_inputs"


def test_missing_sql_input_is_an_invalid_argument(cli_environment: dict[str, str]) -> None:
    result = run_cli(cli_environment, "sql", "read")

    payload = decode_one_json(result.stdout)
    assert result.returncode == 2
    assert result.stderr == ""
    error = error_of(payload)
    assert error["code"] == "invalid_argument"
    details = as_array(error["details"])
    assert as_object(details[0])["error_type"] == "missing_sql"


def test_parameter_object_is_rejected(cli_environment: dict[str, str], tmp_path: Path) -> None:
    params_file = tmp_path / "params.json"
    params_file.write_text('{"id": 1}', encoding="utf-8")

    result = run_cli(
        cli_environment,
        "sql",
        "read",
        "--sql",
        "SELECT ID FROM t WHERE ID = ?",
        "--params-file",
        str(params_file),
    )

    payload = decode_one_json(result.stdout)
    assert result.returncode == 3
    assert result.stderr == ""
    error = error_of(payload)
    assert error["code"] == "input_error"
    details = as_array(error["details"])
    assert as_object(details[0])["error_type"] == "invalid_params_type"


def test_parameter_array_reports_secret_free_diagnostics(
    cli_environment: dict[str, str], tmp_path: Path
) -> None:
    params_file = tmp_path / "params.json"
    params_file.write_text('[7, "alpha"]', encoding="utf-8")

    result = run_cli(
        cli_environment,
        "sql",
        "read",
        "--sql",
        "SELECT ID FROM t WHERE ID = ? AND NAME = ?",
        "--params-file",
        str(params_file),
    )

    payload = decode_one_json(result.stdout)
    assert result.returncode == 0
    assert result.stderr == ""
    data = as_object(payload["data"])
    parameters = as_object(data["parameters"])
    assert parameters["source"] == "params_file"
    assert parameters["kind"] == "array"
    assert parameters["count"] == 2
    assert "alpha" not in result.stdout


def test_write_accepts_an_explicit_rollback_transaction(cli_environment: dict[str, str]) -> None:
    result = run_cli(
        cli_environment,
        "sql",
        "write",
        "--sql",
        "UPDATE t SET x = 1",
        "--transaction",
        "rollback",
    )

    payload = decode_one_json(result.stdout)
    assert result.returncode == 0
    assert result.stderr == ""
    data = as_object(payload["data"])
    assert data["action"] == "write"


def test_missing_profile_is_a_profile_not_found_failure(cli_environment: dict[str, str]) -> None:
    result = run_cli(cli_environment, "--profile", "absent", "sql", "read", "--sql", "SELECT 1")

    payload = decode_one_json(result.stdout)
    assert result.returncode == 4
    assert result.stderr == ""
    error = error_of(payload)
    assert error["code"] == "profile_not_found"


def test_sql_file_dash_reads_stdin_and_preserves_the_source(cli_environment: dict[str, str]) -> None:
    result = run_cli(cli_environment, "sql", "read", "--sql-file", "-", stdin_text="SELECT 1")

    payload = decode_one_json(result.stdout)
    assert result.returncode == 0
    assert result.stderr == ""
    data = as_object(payload["data"])
    sql = as_object(data["sql"])
    assert sql["source"] == "stdin"
    meta = as_object(payload["meta"])
    assert meta["input_source"] == "stdin"


def test_sql_text_and_parameter_values_are_never_echoed(
    cli_environment: dict[str, str], tmp_path: Path
) -> None:
    params_file = tmp_path / "params.json"
    params_file.write_text('["super-secret-parameter"]', encoding="utf-8")

    result = run_cli(
        cli_environment,
        "sql",
        "read",
        "--sql",
        "SELECT 'super-secret-literal' FROM t WHERE ID = ?",
        "--params-file",
        str(params_file),
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert "super-secret-literal" not in result.stdout
    assert "super-secret-parameter" not in result.stdout


def test_sql_help_lists_benchmark_and_compare(cli_environment: dict[str, str]) -> None:
    result = run_cli(cli_environment, "sql", "--help")

    assert result.returncode == 0
    assert result.stderr == ""
    assert "benchmark" in result.stdout
    assert "compare" in result.stdout


def test_benchmark_without_a_profile_reports_local_diagnostics(cli_environment: dict[str, str]) -> None:
    result = run_cli(
        cli_environment,
        "sql",
        "benchmark",
        "--sql",
        "SELECT 1 AS N FROM DUAL",
        "--iterations",
        "2",
        "--warmup-iterations",
        "0",
    )

    payload = decode_one_json(result.stdout)
    assert result.returncode == 0
    assert result.stderr == ""
    data = as_object(payload["data"])
    assert data["status"] == "parsed"
    assert data["action"] == "benchmark"
    sql = as_object(data["sql"])
    assert sql["statement_type"] == "select"
    assert sql["read_only"] is True


def test_benchmark_rejects_write_sql_during_local_diagnostics(cli_environment: dict[str, str]) -> None:
    result = run_cli(cli_environment, "sql", "benchmark", "--sql", "UPDATE t SET N = 1")

    payload = decode_one_json(result.stdout)
    assert result.returncode == 2
    assert result.stderr == ""
    error = error_of(payload)
    assert error["code"] == "unsupported_sql"
    details = as_array(error["details"])
    assert as_object(details[0])["error_type"] == "policy_violation"


def test_compare_without_a_profile_reports_both_diagnostics(cli_environment: dict[str, str]) -> None:
    result = run_cli(
        cli_environment,
        "sql",
        "compare",
        "--left-sql",
        "SELECT 1 AS ID",
        "--right-sql",
        "SELECT 2 AS ID",
        "--key-column",
        "ID",
    )

    payload = decode_one_json(result.stdout)
    assert result.returncode == 0
    assert result.stderr == ""
    data = as_object(payload["data"])
    assert data["status"] == "parsed"
    assert data["action"] == "compare"
    assert data["sql"] is None
    comparison = as_object(data["comparison"])
    left = as_object(comparison["left"])
    right = as_object(comparison["right"])
    assert left["statement_type"] == "select"
    assert left["read_only"] is True
    assert left["source"] == "inline"
    assert right["statement_type"] == "select"
    assert right["read_only"] is True


@pytest.mark.parametrize(
    ("left_sql", "right_sql", "expected_code"),
    [
        ("UPDATE t SET N = 1", "SELECT 1 AS ID", "unsupported_sql"),
        ("SELECT 1 AS ID", "DELETE FROM t", "unsupported_sql"),
        ("SELECT 'unterminated", "SELECT 1 AS ID", "invalid_sql"),
        ("SELECT 1 AS ID", "SELECT 'unterminated", "invalid_sql"),
    ],
)
def test_compare_validates_both_inputs_during_local_diagnostics(
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
    error = error_of(payload)
    assert error["code"] == expected_code


def test_compare_missing_right_sql_is_an_invalid_argument(cli_environment: dict[str, str]) -> None:
    result = run_cli(cli_environment, "sql", "compare", "--left-sql", "SELECT 1 AS ID")

    payload = decode_one_json(result.stdout)
    assert result.returncode == 2
    assert result.stderr == ""
    error = error_of(payload)
    assert error["code"] == "invalid_argument"
    details = as_array(error["details"])
    assert as_object(details[0])["error_type"] == "missing_sql"


def test_compare_sql_file_dash_does_not_accept_stdin(cli_environment: dict[str, str]) -> None:
    result = run_cli(
        cli_environment,
        "sql",
        "compare",
        "--left-sql-file",
        "-",
        "--right-sql",
        "SELECT 1 AS ID",
        stdin_text="SELECT 1 AS ID",
    )

    payload = decode_one_json(result.stdout)
    assert result.returncode == 2
    assert result.stderr == ""
    error = error_of(payload)
    assert error["code"] == "invalid_argument"
    details = as_array(error["details"])
    assert as_object(details[0])["argument"] == "--left-sql/--left-sql-file"
