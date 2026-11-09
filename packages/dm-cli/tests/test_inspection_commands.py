"""Process-level contract tests for ``db-dm server`` and ``db-dm schema``."""

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


def run_cli(cli_environment: dict[str, str], *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "dm_cli", *arguments],
        capture_output=True,
        check=False,
        env=cli_environment,
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


def test_help_lists_the_server_and_schema_command_groups(cli_environment: dict[str, str]) -> None:
    result = run_cli(cli_environment, "help")

    assert result.returncode == 0
    assert "server" in result.stdout
    assert "schema" in result.stdout
    assert result.stderr == ""


def test_server_inspect_without_a_profile_is_a_profile_not_found_failure(
    cli_environment: dict[str, str],
) -> None:
    result = run_cli(cli_environment, "server", "inspect")

    payload = decode_one_json(result.stdout)
    assert result.returncode == 4
    assert result.stderr == ""
    assert error_of(payload)["code"] == "profile_not_found"
    meta = as_object(payload["meta"])
    assert meta["command_group"] == "server"
    assert meta["action"] == "inspect"


def test_server_capabilities_without_a_profile_is_a_profile_not_found_failure(
    cli_environment: dict[str, str],
) -> None:
    result = run_cli(cli_environment, "server", "capabilities")

    payload = decode_one_json(result.stdout)
    assert result.returncode == 4
    assert result.stderr == ""
    assert error_of(payload)["code"] == "profile_not_found"
    meta = as_object(payload["meta"])
    assert meta["command_group"] == "server"
    assert meta["action"] == "capabilities"


def test_schema_databases_accepts_all_and_requires_a_profile(
    cli_environment: dict[str, str],
) -> None:
    result = run_cli(cli_environment, "schema", "databases", "--all")

    payload = decode_one_json(result.stdout)
    assert result.returncode == 4
    assert result.stderr == ""
    assert error_of(payload)["code"] == "profile_not_found"
    meta = as_object(payload["meta"])
    assert meta["command_group"] == "schema"
    assert meta["action"] == "databases"


def test_schema_tables_schema_and_database_options_are_mutually_exclusive(
    cli_environment: dict[str, str],
) -> None:
    result = run_cli(
        cli_environment,
        "schema",
        "tables",
        "--schema",
        "APP",
        "--database",
        "OTHER",
    )

    payload = decode_one_json(result.stdout)
    assert result.returncode == 2
    assert result.stderr == ""
    error = error_of(payload)
    assert error["code"] == "invalid_argument"
    details = as_array(error["details"])
    assert as_object(details[0])["error_type"] == "mutually_exclusive_inputs"


def test_schema_describe_schema_and_database_options_are_mutually_exclusive(
    cli_environment: dict[str, str],
) -> None:
    result = run_cli(
        cli_environment,
        "schema",
        "describe",
        "--table",
        "T",
        "--schema",
        "APP",
        "--database",
        "OTHER",
    )

    payload = decode_one_json(result.stdout)
    assert result.returncode == 2
    assert result.stderr == ""
    error = error_of(payload)
    assert error["code"] == "invalid_argument"
    details = as_array(error["details"])
    assert as_object(details[0])["error_type"] == "mutually_exclusive_inputs"


def test_schema_describe_requires_a_table_option(cli_environment: dict[str, str]) -> None:
    result = run_cli(cli_environment, "schema", "describe", "--schema", "APP")

    payload = decode_one_json(result.stdout)
    assert result.returncode == 2
    assert result.stderr == ""
    error = error_of(payload)
    assert error["code"] == "invalid_argument"
    details = as_array(error["details"])
    assert as_object(details[0])["error_type"] == "argument_syntax"


def test_schema_tables_without_a_profile_is_a_profile_not_found_failure(
    cli_environment: dict[str, str],
) -> None:
    result = run_cli(cli_environment, "schema", "tables", "--schema", "APP")

    payload = decode_one_json(result.stdout)
    assert result.returncode == 4
    assert result.stderr == ""
    assert error_of(payload)["code"] == "profile_not_found"


def test_schema_help_lists_the_indexes_and_stats_commands(cli_environment: dict[str, str]) -> None:
    result = run_cli(cli_environment, "schema", "--help")

    assert result.returncode == 0
    assert result.stderr == ""
    assert "indexes" in result.stdout
    assert "stats" in result.stdout


def test_schema_indexes_help_lists_the_table_and_schema_options(
    cli_environment: dict[str, str],
) -> None:
    result = run_cli(cli_environment, "schema", "indexes", "--help")

    assert result.returncode == 0
    assert result.stderr == ""
    assert "--table" in result.stdout
    assert "--schema" in result.stdout
    assert "--database" in result.stdout


def test_schema_stats_help_lists_the_table_and_schema_options(
    cli_environment: dict[str, str],
) -> None:
    result = run_cli(cli_environment, "schema", "stats", "--help")

    assert result.returncode == 0
    assert result.stderr == ""
    assert "--table" in result.stdout
    assert "--schema" in result.stdout
    assert "--database" in result.stdout


def test_schema_indexes_requires_a_table_option(cli_environment: dict[str, str]) -> None:
    result = run_cli(cli_environment, "schema", "indexes", "--schema", "APP")

    payload = decode_one_json(result.stdout)
    assert result.returncode == 2
    assert result.stderr == ""
    error = error_of(payload)
    assert error["code"] == "invalid_argument"
    details = as_array(error["details"])
    assert as_object(details[0])["error_type"] == "argument_syntax"


def test_schema_indexes_schema_and_database_options_are_mutually_exclusive(
    cli_environment: dict[str, str],
) -> None:
    result = run_cli(
        cli_environment,
        "schema",
        "indexes",
        "--table",
        "T",
        "--schema",
        "APP",
        "--database",
        "OTHER",
    )

    payload = decode_one_json(result.stdout)
    assert result.returncode == 2
    assert result.stderr == ""
    error = error_of(payload)
    assert error["code"] == "invalid_argument"
    details = as_array(error["details"])
    assert as_object(details[0])["error_type"] == "mutually_exclusive_inputs"


def test_schema_stats_schema_and_database_options_are_mutually_exclusive(
    cli_environment: dict[str, str],
) -> None:
    result = run_cli(
        cli_environment,
        "schema",
        "stats",
        "--schema",
        "APP",
        "--database",
        "OTHER",
    )

    payload = decode_one_json(result.stdout)
    assert result.returncode == 2
    assert result.stderr == ""
    error = error_of(payload)
    assert error["code"] == "invalid_argument"
    details = as_array(error["details"])
    assert as_object(details[0])["error_type"] == "mutually_exclusive_inputs"


def test_schema_indexes_without_a_profile_is_a_profile_not_found_failure(
    cli_environment: dict[str, str],
) -> None:
    result = run_cli(cli_environment, "schema", "indexes", "--table", "T")

    payload = decode_one_json(result.stdout)
    assert result.returncode == 4
    assert result.stderr == ""
    assert error_of(payload)["code"] == "profile_not_found"
    meta = as_object(payload["meta"])
    assert meta["command_group"] == "schema"
    assert meta["action"] == "indexes"


def test_schema_stats_without_a_profile_is_a_profile_not_found_failure(
    cli_environment: dict[str, str],
) -> None:
    result = run_cli(cli_environment, "schema", "stats")

    payload = decode_one_json(result.stdout)
    assert result.returncode == 4
    assert result.stderr == ""
    assert error_of(payload)["code"] == "profile_not_found"
    meta = as_object(payload["meta"])
    assert meta["command_group"] == "schema"
    assert meta["action"] == "stats"


def test_server_parameters_help_lists_the_filter_and_all_options(
    cli_environment: dict[str, str],
) -> None:
    result = run_cli(cli_environment, "server", "parameters", "--help")

    assert result.returncode == 0
    assert result.stderr == ""
    assert "--filter" in result.stdout
    assert "--all" in result.stdout


def test_server_parameters_without_a_profile_is_a_profile_not_found_failure(
    cli_environment: dict[str, str],
) -> None:
    result = run_cli(cli_environment, "server", "parameters", "--filter", "PWD", "--all")

    payload = decode_one_json(result.stdout)
    assert result.returncode == 4
    assert result.stderr == ""
    assert error_of(payload)["code"] == "profile_not_found"
    meta = as_object(payload["meta"])
    assert meta["command_group"] == "server"
    assert meta["action"] == "parameters"


def test_schema_help_lists_the_catalog_commands(cli_environment: dict[str, str]) -> None:
    result = run_cli(cli_environment, "schema", "--help")

    assert result.returncode == 0
    assert result.stderr == ""
    assert "ddl" in result.stdout
    assert "constraints" in result.stdout
    assert "objects" in result.stdout


def test_schema_ddl_help_lists_type_name_and_schema_options(
    cli_environment: dict[str, str],
) -> None:
    result = run_cli(cli_environment, "schema", "ddl", "--help")

    assert result.returncode == 0
    assert result.stderr == ""
    assert "--type" in result.stdout
    assert "--name" in result.stdout
    assert "--schema" in result.stdout
    assert "--database" in result.stdout
    assert "table" in result.stdout


def test_schema_ddl_requires_a_name_option(cli_environment: dict[str, str]) -> None:
    result = run_cli(cli_environment, "schema", "ddl", "--schema", "APP")

    payload = decode_one_json(result.stdout)
    assert result.returncode == 2
    assert result.stderr == ""
    error = error_of(payload)
    assert error["code"] == "invalid_argument"
    details = as_array(error["details"])
    assert as_object(details[0])["error_type"] == "argument_syntax"


def test_schema_ddl_rejects_an_unknown_object_type(cli_environment: dict[str, str]) -> None:
    result = run_cli(cli_environment, "schema", "ddl", "--type", "bogus", "--name", "T")

    payload = decode_one_json(result.stdout)
    assert result.returncode == 2
    assert result.stderr == ""
    error = error_of(payload)
    assert error["code"] == "invalid_argument"
    details = as_array(error["details"])
    assert as_object(details[0])["error_type"] == "argument_syntax"


def test_schema_ddl_schema_and_database_options_are_mutually_exclusive(
    cli_environment: dict[str, str],
) -> None:
    result = run_cli(
        cli_environment,
        "schema",
        "ddl",
        "--name",
        "T",
        "--schema",
        "APP",
        "--database",
        "OTHER",
    )

    payload = decode_one_json(result.stdout)
    assert result.returncode == 2
    assert result.stderr == ""
    error = error_of(payload)
    assert error["code"] == "invalid_argument"
    details = as_array(error["details"])
    assert as_object(details[0])["error_type"] == "mutually_exclusive_inputs"


def test_schema_ddl_without_a_profile_is_a_profile_not_found_failure(
    cli_environment: dict[str, str],
) -> None:
    result = run_cli(cli_environment, "schema", "ddl", "--type", "table", "--name", "T")

    payload = decode_one_json(result.stdout)
    assert result.returncode == 4
    assert result.stderr == ""
    assert error_of(payload)["code"] == "profile_not_found"
    meta = as_object(payload["meta"])
    assert meta["command_group"] == "schema"
    assert meta["action"] == "ddl"


def test_schema_constraints_schema_and_database_options_are_mutually_exclusive(
    cli_environment: dict[str, str],
) -> None:
    result = run_cli(
        cli_environment,
        "schema",
        "constraints",
        "--schema",
        "APP",
        "--database",
        "OTHER",
    )

    payload = decode_one_json(result.stdout)
    assert result.returncode == 2
    assert result.stderr == ""
    error = error_of(payload)
    assert error["code"] == "invalid_argument"
    details = as_array(error["details"])
    assert as_object(details[0])["error_type"] == "mutually_exclusive_inputs"


def test_schema_constraints_without_a_profile_is_a_profile_not_found_failure(
    cli_environment: dict[str, str],
) -> None:
    result = run_cli(cli_environment, "schema", "constraints", "--table", "T")

    payload = decode_one_json(result.stdout)
    assert result.returncode == 4
    assert result.stderr == ""
    assert error_of(payload)["code"] == "profile_not_found"
    meta = as_object(payload["meta"])
    assert meta["command_group"] == "schema"
    assert meta["action"] == "constraints"


def test_schema_objects_accepts_type_and_requires_a_profile(
    cli_environment: dict[str, str],
) -> None:
    result = run_cli(cli_environment, "schema", "objects", "--type", "index", "--schema", "APP")

    payload = decode_one_json(result.stdout)
    assert result.returncode == 4
    assert result.stderr == ""
    assert error_of(payload)["code"] == "profile_not_found"
    meta = as_object(payload["meta"])
    assert meta["command_group"] == "schema"
    assert meta["action"] == "objects"


def test_schema_help_lists_the_analyze_command(cli_environment: dict[str, str]) -> None:
    result = run_cli(cli_environment, "schema", "--help")

    assert result.returncode == 0
    assert result.stderr == ""
    assert "analyze" in result.stdout


def test_schema_analyze_help_lists_table_partition_and_statistics_options(
    cli_environment: dict[str, str],
) -> None:
    result = run_cli(cli_environment, "schema", "analyze", "--help")

    assert result.returncode == 0
    assert result.stderr == ""
    for option in ("--table", "--schema", "--database", "--partition", "--estimate-percent"):
        assert option in result.stdout
    assert "--cascade" in result.stdout
    assert "--no-cascade" in result.stdout
    assert "--degree" in result.stdout
    assert "--transaction" not in result.stdout


def test_schema_analyze_requires_a_table_option(cli_environment: dict[str, str]) -> None:
    result = run_cli(cli_environment, "schema", "analyze", "--schema", "APP")

    payload = decode_one_json(result.stdout)
    assert result.returncode == 2
    assert result.stderr == ""
    error = error_of(payload)
    assert error["code"] == "invalid_argument"
    details = as_array(error["details"])
    assert as_object(details[0])["error_type"] == "argument_syntax"


def test_schema_analyze_schema_and_database_options_are_mutually_exclusive(
    cli_environment: dict[str, str],
) -> None:
    result = run_cli(
        cli_environment,
        "schema",
        "analyze",
        "--table",
        "T",
        "--schema",
        "APP",
        "--database",
        "OTHER",
    )

    payload = decode_one_json(result.stdout)
    assert result.returncode == 2
    assert result.stderr == ""
    error = error_of(payload)
    assert error["code"] == "invalid_argument"
    details = as_array(error["details"])
    assert as_object(details[0])["error_type"] == "mutually_exclusive_inputs"


@pytest.mark.parametrize("estimate_percent", ("0", "-1", "101"))
def test_schema_analyze_rejects_an_out_of_range_estimate_percent(
    cli_environment: dict[str, str],
    estimate_percent: str,
) -> None:
    result = run_cli(
        cli_environment,
        "schema",
        "analyze",
        "--table",
        "T",
        "--estimate-percent",
        estimate_percent,
    )

    payload = decode_one_json(result.stdout)
    assert result.returncode == 2
    assert result.stderr == ""
    error = error_of(payload)
    assert error["code"] == "invalid_argument"
    details = as_array(error["details"])
    assert as_object(details[0])["error_type"] == "argument_syntax"


def test_schema_analyze_rejects_a_non_positive_degree(cli_environment: dict[str, str]) -> None:
    result = run_cli(cli_environment, "schema", "analyze", "--table", "T", "--degree", "0")

    payload = decode_one_json(result.stdout)
    assert result.returncode == 2
    assert result.stderr == ""
    error = error_of(payload)
    assert error["code"] == "invalid_argument"
    details = as_array(error["details"])
    assert as_object(details[0])["error_type"] == "argument_syntax"


def test_schema_analyze_without_a_profile_is_a_profile_not_found_failure(
    cli_environment: dict[str, str],
) -> None:
    result = run_cli(cli_environment, "schema", "analyze", "--table", "T", "--no-cascade")

    payload = decode_one_json(result.stdout)
    assert result.returncode == 4
    assert result.stderr == ""
    assert error_of(payload)["code"] == "profile_not_found"
    meta = as_object(payload["meta"])
    assert meta["command_group"] == "schema"
    assert meta["action"] == "analyze"
