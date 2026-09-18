from __future__ import annotations

import json
from typing import Any

from click.testing import CliRunner

from db_cli_core import CommandContext
from db_cli_core.enums import DatabaseKind
from db_cli_core.profiles import ConnectionProfileManager, ProfileStore
from db_cli_core.secrets import VolatileSecretStore
from mcp_base.types import ToolResult
from mysql_cli.backend import MySQLBackend
from mysql_cli.config import MySQLConnectionOptions
from mysql_cli.main import cli


class FakeMySQLConnection:
    is_connected = False

    async def connect(self, **_arguments: Any) -> None:
        self.is_connected = True

    async def disconnect(self) -> None:
        self.is_connected = False

    async def get_server_info(self):
        return {}

    def get_pool_status(self):
        return {}


def build_backend(handler):  # type: ignore[no-untyped-def]
    options = MySQLConnectionOptions("localhost", 3306, "root", "", "app", "utf8mb4", 2)
    return MySQLBackend(options, FakeMySQLConnection(), {"mysql_query": handler})  # type: ignore[arg-type]


def test_help_lists_command_groups() -> None:
    result = CliRunner().invoke(cli, ["--help"])

    assert result.exit_code == 0
    for group_name in ("connection", "schema", "sql"):
        assert group_name in result.output


def test_json_query_preserves_sql_and_pagination() -> None:
    captured: dict[str, Any] = {}

    async def query(arguments: dict[str, Any]) -> ToolResult:
        captured.update(arguments)
        return ToolResult.success(data={"rows": [{"id": 1}], "has_more": False})

    backend = build_backend(query)
    try:
        result = CliRunner().invoke(
            cli,
            ["--json", "sql", "query", "--query", "SELECT id FROM users", "--page", "2", "--page-size", "10"],
            obj=CommandContext(backend),
        )

        assert result.exit_code == 0
        assert json.loads(result.output)["data"]["rows"] == [{"id": 1}]
        assert captured == {"query": "SELECT id FROM users", "page": 2, "page_size": 10}
    finally:
        backend.close()


def test_missing_required_query_fails_before_backend() -> None:
    async def unused(_arguments: dict[str, Any]) -> ToolResult:
        raise AssertionError("backend must not be called")

    backend = build_backend(unused)
    try:
        result = CliRunner().invoke(cli, ["sql", "query"], obj=CommandContext(backend))

        assert result.exit_code == 2
        assert "--query" in result.output
    finally:
        backend.close()


def test_profile_set_binds_directory_and_is_used_without_connection_arguments(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    project = tmp_path / "project"
    project.mkdir()
    secret_store = VolatileSecretStore()
    manager = ConnectionProfileManager(DatabaseKind.MYSQL, ProfileStore(tmp_path / "connections.json", secret_store))
    backend = build_backend(lambda _arguments: None)
    runner = CliRunner()
    try:
        configured = runner.invoke(
            cli,
            [
                "--json",
                "profile",
                "set",
                "analytics",
                "--path",
                str(project),
                "--host",
                "analytics.local",
                "--port",
                "3307",
                "--user",
                "agent",
                "--password",
                "secret",
                "--database",
                "warehouse",
            ],
            obj=CommandContext(backend, profile_manager=manager),
        )
        current = runner.invoke(
            cli,
            ["--json", "profile", "current", "--path", str(project / "child")],
            obj=CommandContext(backend, profile_manager=manager),
        )

        assert configured.exit_code == 0, configured.output
        assert "secret" not in manager.store.path.read_text(encoding="utf-8")
        assert secret_store.get(DatabaseKind.MYSQL, "analytics") == "secret"
        payload = json.loads(current.output)
        assert current.exit_code == 0, current.output
        assert payload["profile"] == "analytics"
        assert payload["data"] == {
            "profile": "analytics",
            "source": "directory",
            "bound_directory": str(project.resolve()),
            "host": "analytics.local",
            "port": 3307,
            "user": "agent",
            "password": "****",
            "database": "warehouse",
            "charset": "utf8mb4",
            "connection_timeout": 2,
        }

        monkeypatch.chdir(project)
        status = runner.invoke(
            cli,
            ["--json", "connection", "status"],
            obj=CommandContext(backend, profile_manager=manager),
        )
        status_payload = json.loads(status.output)
        status_connection = status_payload["data"]["config"]
        assert status.exit_code == 0, status.output
        assert status_payload["profile"] == "analytics"
        assert status_connection["database"] == "warehouse"
    finally:
        backend.close()


def test_profile_list_reports_current_directory_connection(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    manager = ConnectionProfileManager(
        DatabaseKind.MYSQL, ProfileStore(tmp_path / "connections.json", VolatileSecretStore())
    )
    manager.set(
        "app",
        MySQLConnectionOptions("db.local", 3306, "agent", "", "bound_db", "utf8mb4", 2).profile_settings(),
        project,
    )
    backend = build_backend(lambda _arguments: None)
    try:
        result = CliRunner().invoke(
            cli,
            ["--json", "profile", "list"],
            obj=CommandContext(backend, profile_manager=manager),
        )

        payload = json.loads(result.output)
        assert result.exit_code == 0, result.output
        assert payload["profile"] == "app"
        assert "connection" not in payload
    finally:
        backend.close()


def test_invalid_profile_returns_structured_json_error(tmp_path) -> None:  # type: ignore[no-untyped-def]
    backend = build_backend(lambda _arguments: None)
    manager = ConnectionProfileManager(
        DatabaseKind.MYSQL, ProfileStore(tmp_path / "connections.json", VolatileSecretStore())
    )
    try:
        result = CliRunner().invoke(
            cli,
            ["--json", "--profile", "missing", "connection", "status"],
            obj=CommandContext(backend, profile_manager=manager),
        )

        payload = json.loads(result.output)
        assert result.exit_code == 1
        assert payload["status"] == "error"
        assert payload["profile"] is None
    finally:
        backend.close()


def test_interactive_context_keeps_use_override_with_directory_binding(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    manager = ConnectionProfileManager(
        DatabaseKind.MYSQL, ProfileStore(tmp_path / "connections.json", VolatileSecretStore())
    )
    manager.set(
        "app",
        MySQLConnectionOptions("db.local", 3306, "agent", "", "app", "utf8mb4", 2).profile_settings(),
        project,
    )
    backend = build_backend(lambda _arguments: None)
    context = CommandContext(backend, profile_manager=manager)
    runner = CliRunner()
    try:
        switched = runner.invoke(cli, ["--json", "use", "analytics"], obj=context)
        status = runner.invoke(cli, ["--json", "connection", "status"], obj=context)

        assert switched.exit_code == 0, switched.output
        assert json.loads(status.output)["data"]["config"]["database"] == "analytics"
        assert json.loads(status.output)["profile"] is None
    finally:
        backend.close()


def test_clearing_binding_restores_backend_baseline(tmp_path) -> None:  # type: ignore[no-untyped-def]
    project = tmp_path / "project"
    project.mkdir()
    manager = ConnectionProfileManager(
        DatabaseKind.MYSQL, ProfileStore(tmp_path / "connections.json", VolatileSecretStore())
    )
    manager.set(
        "bound",
        MySQLConnectionOptions("bound.local", 3306, "agent", "", "bound_db", "utf8mb4", 2).profile_settings(),
        project,
    )
    backend = build_backend(lambda _arguments: None)
    context = CommandContext(backend, profile_manager=manager)
    runner = CliRunner()
    try:
        runner.invoke(cli, ["--json", "profile", "current", "--path", str(project)], obj=context)
        cleared = runner.invoke(cli, ["--json", "profile", "clear", "--path", str(project)], obj=context)

        assert json.loads(cleared.output)["profile"] is None
        connection = context.connection_info()
        assert cleared.exit_code == 0, cleared.output
        assert connection["source"] == "default"
        assert connection["profile"] is None
        assert connection["host"] == "localhost"
        assert connection["database"] == "app"
    finally:
        backend.close()


def test_profile_set_updates_only_supplied_fields(tmp_path) -> None:  # type: ignore[no-untyped-def]
    manager = ConnectionProfileManager(
        DatabaseKind.MYSQL, ProfileStore(tmp_path / "connections.json", VolatileSecretStore())
    )
    runner = CliRunner()
    original_backend = build_backend(lambda _arguments: None)
    replacement_backend = build_backend(lambda _arguments: None)
    try:
        created = runner.invoke(
            cli,
            ["--json", "profile", "set", "app", "--no-bind", "--host", "db.internal", "--port", "3307"],
            obj=CommandContext(original_backend, profile_manager=manager),
        )
        updated = runner.invoke(
            cli,
            ["--json", "profile", "set", "app", "--no-bind", "--database", "analytics"],
            obj=CommandContext(replacement_backend, profile_manager=manager),
        )
        shown = runner.invoke(
            cli,
            ["--json", "profile", "show", "app"],
            obj=CommandContext(replacement_backend, profile_manager=manager),
        )

        assert created.exit_code == 0, created.output
        assert updated.exit_code == 0, updated.output
        connection = json.loads(shown.output)["data"]
        assert connection["host"] == "db.internal"
        assert connection["port"] == 3307
        assert connection["database"] == "analytics"
    finally:
        original_backend.close()
        replacement_backend.close()
