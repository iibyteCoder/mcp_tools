from __future__ import annotations

from typing import Any

from mcp_base.types import ToolResult, ToolStatus
from mysql_cli.backend import MySQLBackend
from mysql_cli.catalog import build_catalog
from mysql_cli.config import MySQLConnectionOptions


class FakeMySQLConnection:
    def __init__(self) -> None:
        self.is_connected = False
        self.connection_arguments: dict[str, Any] = {}

    async def connect(self, **arguments: Any) -> None:
        self.connection_arguments = arguments
        self.is_connected = True

    async def disconnect(self) -> None:
        self.is_connected = False

    async def get_server_info(self) -> dict[str, Any]:
        return {"server_version": "test"}

    def get_pool_status(self) -> dict[str, Any]:
        return {"pool_size": 1}


def mysql_options(database: str = "app") -> MySQLConnectionOptions:
    return MySQLConnectionOptions("localhost", 3306, "root", "secret", database, "utf8mb4", 3)


def test_url_then_explicit_overrides_apply_in_order() -> None:
    options = mysql_options().apply_url("mysql://alice:p%40ss@db.local:3307/source")
    options = options.apply_overrides(host="override.local", database="analytics")

    assert options.host == "override.local"
    assert options.port == 3307
    assert options.user == "alice"
    assert options.password == "p@ss"
    assert options.database == "analytics"


def test_safe_info_masks_password() -> None:
    safe_info = mysql_options().safe_info()

    assert safe_info["password"] == "****"
    assert "secret" not in safe_info.values()


def test_catalog_covers_all_8_commands() -> None:
    catalog = build_catalog()

    assert len(catalog) == 8
    assert len({descriptor.tool_name for descriptor in catalog}) == 8


def test_backend_connects_lazily_and_dispatches() -> None:
    connection = FakeMySQLConnection()

    async def query(arguments: dict[str, Any]) -> ToolResult:
        return ToolResult.success(data={"rows": [{"query": arguments["query"]}]})

    backend = MySQLBackend(
        options=mysql_options(),
        connection=connection,  # type: ignore[arg-type]
        handlers={"mysql_query": query},
    )
    try:
        result = backend.invoke("mysql_query", {"query": "SELECT 1"})

        assert result.data == {"rows": [{"query": "SELECT 1"}]}
        assert connection.connection_arguments["database"] == "app"
        assert connection.connection_arguments["connection_timeout"] == 3
    finally:
        backend.close()


def test_backend_switches_database_and_reconnects() -> None:
    connection = FakeMySQLConnection()
    backend = MySQLBackend(options=mysql_options(), connection=connection, handlers={})  # type: ignore[arg-type]
    try:
        result = backend.switch_target("analytics")

        assert result.status is ToolStatus.SUCCESS
        assert backend.target_label == "analytics"
        assert connection.connection_arguments["database"] == "analytics"
    finally:
        backend.close()


def test_backend_rejects_blank_database() -> None:
    connection = FakeMySQLConnection()
    backend = MySQLBackend(options=mysql_options(), connection=connection, handlers={})  # type: ignore[arg-type]
    try:
        result = backend.switch_target("  ")

        assert result.status is ToolStatus.ERROR
        assert connection.is_connected is False
    finally:
        backend.close()
