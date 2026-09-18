from __future__ import annotations

from typing import Any

from mcp_base.types import ToolResult, ToolStatus
from redis_cli.backend import RedisBackend
from redis_cli.catalog import build_catalog
from redis_cli.config import RedisConnectionOptions


class FakeRedisConnection:
    def __init__(self) -> None:
        self.is_connected = False
        self.connection_arguments: dict[str, Any] = {}

    async def connect(self, **arguments: Any) -> None:
        self.connection_arguments = arguments
        self.is_connected = True

    async def disconnect(self) -> None:
        self.is_connected = False


def redis_options(database: int = 0) -> RedisConnectionOptions:
    return RedisConnectionOptions("localhost", 6379, "", "secret", database, 3)


def test_url_then_explicit_overrides_apply_in_order() -> None:
    options = redis_options().apply_url("redis://alice:p%40ss@cache.local:6380/4")
    options = options.apply_overrides(host="override.local", database=7)

    assert options.host == "override.local"
    assert options.port == 6380
    assert options.username == "alice"
    assert options.password == "p@ss"
    assert options.database == 7


def test_safe_info_masks_password() -> None:
    safe_info = redis_options().safe_info()

    assert safe_info["password"] == "****"
    assert "secret" not in safe_info.values()


def test_invalid_url_is_rejected() -> None:
    try:
        redis_options().apply_url("http://localhost:6379/0")
    except ValueError as exc:
        assert "redis://" in str(exc)
    else:
        raise AssertionError("invalid Redis URL was accepted")


def test_catalog_covers_all_53_commands() -> None:
    catalog = build_catalog()

    assert len(catalog) == 53
    assert len({descriptor.tool_name for descriptor in catalog}) == 53


def test_backend_connects_lazily_and_dispatches() -> None:
    connection = FakeRedisConnection()

    async def get_value(arguments: dict[str, Any]) -> ToolResult:
        return ToolResult.success(data={"key": arguments["key"], "value": "found"})

    backend = RedisBackend(
        options=redis_options(),
        connection=connection,  # type: ignore[arg-type]
        handlers={"redis_get": get_value},
    )
    try:
        result = backend.invoke("redis_get", {"key": "sample"})

        assert result.data == {"key": "sample", "value": "found"}
        assert connection.is_connected is True
        assert connection.connection_arguments["connection_timeout"] == 3
    finally:
        backend.close()


def test_backend_switches_database_and_reconnects() -> None:
    connection = FakeRedisConnection()
    backend = RedisBackend(options=redis_options(), connection=connection, handlers={})  # type: ignore[arg-type]
    try:
        result = backend.switch_target("9")

        assert result.status is ToolStatus.SUCCESS
        assert backend.target_label == "db9"
        assert connection.connection_arguments["db"] == 9
    finally:
        backend.close()


def test_backend_rejects_invalid_database_without_connecting() -> None:
    connection = FakeRedisConnection()
    backend = RedisBackend(options=redis_options(), connection=connection, handlers={})  # type: ignore[arg-type]
    try:
        result = backend.switch_target("not-a-number")

        assert result.status is ToolStatus.ERROR
        assert connection.is_connected is False
    finally:
        backend.close()
