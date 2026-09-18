"""Public output and named-target behavior across both CLIs."""

import json

import pytest
from click.testing import CliRunner

from db_cli_core.context import CommandContext
from db_cli_core.enums import DatabaseKind
from db_cli_core.profiles import ConnectionProfileManager, ProfileStore
from db_cli_core.secrets import VolatileSecretStore
from mcp_base.types import ToolResult
from mysql_cli.backend import MySQLBackend
from mysql_cli.config import MySQLConnectionOptions
from mysql_cli.main import cli as mysql_cli
from redis_cli.backend import RedisBackend
from redis_cli.config import RedisConnectionOptions
from redis_cli.main import cli as redis_cli


class RecordingConnection:
    is_connected = False

    async def connect(self, **arguments):
        self.arguments = arguments
        self.is_connected = True

    async def disconnect(self):
        self.is_connected = False


@pytest.fixture(params=[DatabaseKind.MYSQL, DatabaseKind.REDIS])
def session(request, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    connection = RecordingConnection()

    async def read(_arguments):
        return ToolResult.success(data={"ok": True})

    if request.param == DatabaseKind.MYSQL:
        backend = MySQLBackend(
            MySQLConnectionOptions("db.local", 3306, "agent", "secret", "app", "utf8mb4", 2),
            connection,
            {"mysql_query": read},
        )
        cli, command, target = mysql_cli, ["sql", "query", "--query", "SELECT 1"], "other"
    else:
        backend = RedisBackend(
            RedisConnectionOptions("cache.local", 6379, "", "secret", 0, 2),
            connection,
            {"redis_ping": read},
        )
        cli, command, target = redis_cli, ["server", "ping"], "2"
    manager = ConnectionProfileManager(request.param, ProfileStore(tmp_path / "profiles.json", VolatileSecretStore()))
    manager.set("app-dev", backend.build_profile(), tmp_path)
    context = CommandContext(backend, profile_manager=manager)

    def invoke(*args):
        return CliRunner().invoke(cli, list(args), obj=context)

    yield invoke, command, target, context, connection, manager
    backend.close()


def test_normal_result_only_includes_profile_name(session):
    invoke, command, _, _, _, _ = session
    result = invoke("--json", *command)
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {"status": "success", "data": {"ok": True}, "profile": "app-dev"}


def test_human_output_only_includes_profile_name(session):
    invoke, command, _, _, _, _ = session
    result = invoke(*command)
    assert result.exit_code == 0, result.output
    assert "app-dev" in result.output
    assert "host" not in result.output
    assert "secret" not in result.output


def test_details_are_available_on_demand(session):
    invoke, _, _, _, _, _ = session
    result = invoke("--json", "profile", "show", "app-dev")
    payload = json.loads(result.output)
    assert payload["profile"] == "app-dev"
    assert payload["data"]["host"] in {"db.local", "cache.local"}
    assert payload["data"]["password"] == "****"
    assert "connection" not in payload


def test_temporary_override_does_not_mislabel_actual_connection(session):
    invoke, command, _, _, connection, _ = session
    assert invoke("--json", *command).exit_code == 0
    result = invoke("--json", "--host", "other.local", *command)
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["profile"] is None
    assert connection.arguments["host"] == "other.local"
    restored = invoke("--json", "--profile", "app-dev", *command)
    assert json.loads(restored.output)["profile"] == "app-dev"
    assert connection.arguments["host"] != "other.local"


def test_use_does_not_report_original_profile_or_dump_settings(session):
    invoke, command, target, _, _, _ = session
    result = invoke("--json", "use", target)
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["profile"] is None
    assert "data" not in payload
    assert json.loads(invoke("--json", *command).output)["profile"] is None


def test_connection_failure_keeps_name_without_config_dump(session):
    invoke, command, _, _, connection, _ = session

    async def fail(**_arguments):
        raise RuntimeError("connection refused")

    connection.connect = fail
    result = invoke("--json", *command)
    assert result.exit_code == 1
    assert json.loads(result.output) == {
        "status": "error",
        "message": "connection refused",
        "profile": "app-dev",
        "code": "EXECUTION_FAILED",
    }


def test_rename_preserves_settings_secret_and_binding(session):
    invoke, command, _, _, _, manager = session
    original = manager.require("app-dev").settings
    result = invoke("--json", "profile", "rename", "app-dev", "service-dev")
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["profile"] == "service-dev"
    assert manager.find("app-dev") is None
    assert manager.require("service-dev").settings == original
    assert manager.resolve().profile.name == "service-dev"
    assert json.loads(invoke("--json", *command).output)["profile"] == "service-dev"


def test_rename_refuses_existing_destination(session):
    invoke, _, _, _, _, manager = session
    manager.set("existing", manager.require("app-dev").settings)
    result = invoke("--json", "profile", "rename", "app-dev", "existing")
    assert result.exit_code == 1
    assert manager.require("app-dev")
    assert manager.resolve().profile.name == "app-dev"


def test_password_override_is_not_hidden_by_masking(session):
    invoke, command, _, _, connection, _ = session
    result = invoke("--json", "--password", "different-secret", *command)
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["profile"] is None
    assert connection.arguments["password"] == "different-secret"
    assert "different-secret" not in result.output


def test_partial_update_preserves_other_fields_and_binding(session):
    invoke, command, target, _, connection, manager = session
    original = manager.require("app-dev").settings
    database_option = "--database" if manager.database_kind == DatabaseKind.MYSQL else "--db"
    result = invoke(
        "--json",
        "profile",
        "set",
        "app-dev",
        "--port",
        "12345",
        "--password",
        "rotated-secret",
        database_option,
        target,
        "--no-bind",
    )
    assert result.exit_code == 0, result.output
    saved = manager.require("app-dev").settings
    assert saved == original | {
        "port": 12345,
        "password": "rotated-secret",
        "database": target if manager.database_kind == DatabaseKind.MYSQL else int(target),
    }
    assert manager.resolve().profile.name == "app-dev"
    assert "rotated-secret" not in manager.store.path.read_text(encoding="utf-8")
    validated = invoke("--json", "--profile", "app-dev", *command)
    assert validated.exit_code == 0, validated.output
    assert json.loads(validated.output)["profile"] == "app-dev"
    assert connection.arguments["port"] == 12345
    assert connection.arguments["password"] == "rotated-secret"


def test_invalid_configuration_leaves_saved_profile_unchanged(session):
    invoke, _, _, _, _, manager = session
    original = manager.require("app-dev").settings
    result = invoke("--json", "profile", "set", "app-dev", "--port", "70000", "--no-bind")
    assert result.exit_code == 2
    assert manager.require("app-dev").settings == original
