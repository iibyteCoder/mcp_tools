import json
import shutil
import subprocess

import click
import pytest
from click.testing import CliRunner

from db_cli_core.context import CommandContext
from db_cli_core.enums import DatabaseKind, OutputMode
from db_cli_core.execution import execute_safely
from db_cli_core.output import emit_result
from db_cli_core.profiles import ConnectionProfileManager, ProfileStore
from db_cli_core.secrets import VolatileSecretStore
from mcp_base.types import ToolResult
from mysql_cli.backend import MySQLBackend
from mysql_cli.config import MySQLConnectionOptions
from mysql_cli.main import cli as mysql_cli
from redis_cli.backend import RedisBackend
from redis_cli.config import RedisConnectionOptions
from redis_cli.main import cli as redis_cli


class Connection:
    is_connected = False

    async def connect(self, **kwargs):
        self.is_connected = True

    async def disconnect(self):
        self.is_connected = False


@pytest.fixture
def mysql(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    captured = {}

    async def query(args):
        captured.update(args)
        return ToolResult.success(data={"rows": [{"ok": 1}]})

    backend = MySQLBackend(
        MySQLConnectionOptions("localhost", 3306, "root", "", "test", "utf8mb4", 2),
        Connection(),
        {"mysql_query": query},
    )
    manager = ConnectionProfileManager(
        DatabaseKind.MYSQL, ProfileStore(tmp_path / "profiles.json", VolatileSecretStore())
    )
    yield CommandContext(backend, profile_manager=manager), captured
    backend.close()


def test_redundant_success_message_is_omitted():
    @click.command()
    def command():
        emit_result(ToolResult.success("Found 1 row", {"rows": [1]}), OutputMode.JSON, "dev")

    payload = json.loads(CliRunner().invoke(command).output)
    assert payload == {"status": "success", "profile": "dev", "data": {"rows": [1]}}


def test_nonfinite_scores_are_valid_json():
    @click.command()
    def command():
        emit_result(ToolResult.success(data={"scores": [float("inf"), float("-inf"), float("nan")]}), OutputMode.JSON)

    def reject_constant(value):
        raise AssertionError(f"invalid JSON constant: {value}")

    payload = json.loads(CliRunner().invoke(command).output, parse_constant=reject_constant)
    assert payload["data"]["scores"] == ["Infinity", "-Infinity", "NaN"]


@pytest.mark.parametrize(
    "args",
    [
        ["--json", "sql", "query"],
        ["--json", "--port", "70000", "connection", "status"],
        ["--json", "unknown-command"],
    ],
)
def test_parser_failures_are_json(mysql, args):
    context, _ = mysql
    result = CliRunner().invoke(mysql_cli, args, obj=context)
    assert result.exit_code != 0
    payload = json.loads(result.output)
    assert payload["code"] == "INVALID_ARGUMENT"
    assert payload["status"] == "error"


def test_missing_profile_has_stable_code(mysql):
    context, _ = mysql
    result = CliRunner().invoke(mysql_cli, ["--json", "--profile", "missing", "schema", "tables"], obj=context)
    assert json.loads(result.output)["code"] == "PROFILE_NOT_FOUND"


def test_chained_mysql_authentication_error():
    from pymysql.err import OperationalError

    def fail():
        try:
            raise OperationalError(1045, "arbitrary localized text")
        except OperationalError as exc:
            raise ConnectionError("wrapper") from exc

    assert execute_safely(fail).to_dict()["code"] == "AUTH_FAILED"


@pytest.mark.parametrize(
    "exception,code",
    [
        (TimeoutError("timeout"), "TIMEOUT"),
        (ConnectionRefusedError("refused"), "CONNECTION_FAILED"),
        (ValueError("invalid"), "INVALID_ARGUMENT"),
    ],
)
def test_exception_codes(exception, code):
    def fail():
        raise exception

    assert execute_safely(fail).to_dict()["code"] == code


@pytest.mark.parametrize("stdin", [False, True])
def test_query_file_or_stdin(mysql, tmp_path, stdin):
    context, captured = mysql
    sql = "SELECT '中文', 'a\\b', 1 AS ok\n"
    path = tmp_path / "query.sql"
    path.write_text(sql, encoding="utf-8")
    result = CliRunner().invoke(
        mysql_cli,
        ["--json", "sql", "query", "--query-file", "-" if stdin else str(path)],
        obj=context,
        input=sql if stdin else None,
    )
    assert result.exit_code == 0, result.output
    assert captured["query"] == sql


def test_input_sources_are_mutually_exclusive(mysql, tmp_path):
    context, captured = mysql
    path = tmp_path / "query.sql"
    path.write_text("SELECT 2", encoding="utf-8")
    result = CliRunner().invoke(
        mysql_cli, ["--json", "sql", "query", "--query", "SELECT 1", "--query-file", str(path)], obj=context
    )
    assert json.loads(result.output)["code"] == "INVALID_ARGUMENT"
    assert captured == {}


@pytest.mark.parametrize("cli", [mysql_cli, redis_cli])
def test_skill_path_exists_and_references_are_available(cli):
    from pathlib import Path

    result = CliRunner().invoke(cli, ["--json", "skill", "path"])
    assert result.exit_code == 0, result.output
    path = Path(json.loads(result.output)["data"]["path"])
    assert path.is_absolute() and path.is_file()
    assert (path.parent / "references" / "connections.md").is_file()


def test_mysql_execute_does_not_echo_sql(mysql):
    context, _ = mysql

    async def execute(arguments):
        return ToolResult.success(data={"sql": arguments["query"], "affected_rows": 1})

    context.backend._handlers = {"mysql_execute": execute}
    result = CliRunner().invoke(
        mysql_cli, ["--json", "sql", "execute", "--query", "UPDATE example SET n=1"], obj=context
    )
    assert json.loads(result.output)["data"] == {"affected_rows": 1}


def test_pipeline_file_preserves_result_types(tmp_path, monkeypatch):
    from unittest.mock import AsyncMock

    monkeypatch.chdir(tmp_path)
    connection = Connection()
    connection.pipeline_execute = AsyncMock(return_value=[1, True, None, ["a"], {"b": 2}])
    backend = RedisBackend(RedisConnectionOptions("localhost", 6379, "", "", 0, 2), connection)
    manager = ConnectionProfileManager(
        DatabaseKind.REDIS, ProfileStore(tmp_path / "profiles.json", VolatileSecretStore())
    )
    path = tmp_path / "reads.json"
    commands = [["GET", "key"]] * 5
    path.write_text(json.dumps(commands), encoding="utf-8")
    try:
        result = CliRunner().invoke(
            redis_cli,
            ["--json", "server", "pipeline", "--commands-file", str(path)],
            obj=CommandContext(backend, profile_manager=manager),
        )
        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["data"] == {"results": [1, True, None, ["a"], {"b": 2}]}
        connection.pipeline_execute.assert_awaited_once_with(commands)
    finally:
        backend.close()


@pytest.mark.parametrize("name", ["db-mysql", "db-redis"])
def test_installed_discovery_and_parser_error(name):
    from pathlib import Path

    executable = shutil.which(name)
    assert executable, f"{name} must be installed"
    discovered = subprocess.run(
        [executable, "--json", "skill", "path"], capture_output=True, text=True, timeout=15, check=False
    )
    assert discovered.returncode == 0, discovered.stdout + discovered.stderr
    path = Path(json.loads(discovered.stdout)["data"]["path"])
    assert path.is_file()
    assert (path.parent / "references" / "connections.md").is_file()
    failed = subprocess.run(
        [executable, "--json", "--port", "70000", "connection", "status"],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert failed.returncode == 2
    assert json.loads(failed.stdout)["code"] == "INVALID_ARGUMENT"


@pytest.mark.parametrize("text", ["[]", "[[]]", '["GET"]', '[["GET", 1]]', "{}", "invalid json"])
def test_invalid_pipeline_stdin_is_rejected_before_connecting(tmp_path, monkeypatch, text):
    monkeypatch.chdir(tmp_path)
    connection = Connection()
    backend = RedisBackend(RedisConnectionOptions("localhost", 6379, "", "", 0, 2), connection)
    manager = ConnectionProfileManager(
        DatabaseKind.REDIS, ProfileStore(tmp_path / "profiles.json", VolatileSecretStore())
    )
    try:
        result = CliRunner().invoke(
            redis_cli,
            ["--json", "server", "pipeline", "--commands-file", "-"],
            input=text,
            obj=CommandContext(backend, profile_manager=manager),
        )
        assert result.exit_code == 2
        assert json.loads(result.output)["code"] == "INVALID_ARGUMENT"
        assert not connection.is_connected
    finally:
        backend.close()
