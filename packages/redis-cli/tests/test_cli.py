from __future__ import annotations

import json
from typing import Any

from click.testing import CliRunner

from db_cli_core import CommandContext
from db_cli_core.enums import DatabaseKind
from db_cli_core.profiles import ConnectionProfileManager, ProfileStore
from db_cli_core.secrets import VolatileSecretStore
from mcp_base.types import ToolResult
from redis_cli.backend import RedisBackend
from redis_cli.config import RedisConnectionOptions
from redis_cli.main import cli


class FakeRedisConnection:
    is_connected = False

    async def connect(self, **_arguments: Any) -> None:
        self.is_connected = True

    async def disconnect(self) -> None:
        self.is_connected = False


def build_backend(handler, tool_name: str = "redis_hset"):  # type: ignore[no-untyped-def]
    options = RedisConnectionOptions("localhost", 6379, "", "", 0, 2)
    return RedisBackend(options, FakeRedisConnection(), {tool_name: handler})  # type: ignore[arg-type]


def test_help_lists_all_command_groups() -> None:
    result = CliRunner().invoke(cli, ["--help"])

    assert result.exit_code == 0
    for group_name in ("connection", "key", "string", "hash", "list", "set", "zset", "server"):
        assert group_name in result.output


def test_json_command_parses_object_argument() -> None:
    captured: dict[str, Any] = {}

    async def hset(arguments: dict[str, Any]) -> ToolResult:
        captured.update(arguments)
        return ToolResult.success(data={"added": len(arguments["mapping"])})

    backend = build_backend(hset)
    try:
        result = CliRunner().invoke(
            cli,
            ["--json", "hash", "hset", "--key", "user:1", "--mapping", '{"name":"Ada"}'],
            obj=CommandContext(backend),
        )

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["data"]["added"] == 1
        assert payload["profile"] is None
        assert "connection" not in payload
        assert captured == {"key": "user:1", "mapping": {"name": "Ada"}}
    finally:
        backend.close()


def test_invalid_object_argument_fails_before_backend() -> None:
    async def unused(_arguments: dict[str, Any]) -> ToolResult:
        raise AssertionError("backend must not be called")

    backend = build_backend(unused)
    try:
        result = CliRunner().invoke(
            cli,
            ["hash", "hset", "--key", "user:1", "--mapping", "not-json"],
            obj=CommandContext(backend),
        )

        assert result.exit_code == 2
        assert "不是有效 JSON" in result.output
    finally:
        backend.close()


def test_pipeline_parses_nested_command_array() -> None:
    captured: dict[str, Any] = {}

    async def pipeline(arguments: dict[str, Any]) -> ToolResult:
        captured.update(arguments)
        return ToolResult.success(data={"count": len(arguments["commands"])})

    backend = build_backend(pipeline, "redis_pipeline")
    try:
        result = CliRunner().invoke(
            cli,
            ["--json", "server", "pipeline", "--commands", '[["SET","k","v"],["GET","k"]]'],
            obj=CommandContext(backend),
        )

        assert result.exit_code == 0
        assert json.loads(result.output)["data"]["count"] == 2
        assert captured["commands"] == [["SET", "k", "v"], ["GET", "k"]]
    finally:
        backend.close()


def test_different_directories_resolve_independent_profiles(tmp_path) -> None:  # type: ignore[no-untyped-def]
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    manager = ConnectionProfileManager(
        DatabaseKind.REDIS, ProfileStore(tmp_path / "connections.json", VolatileSecretStore())
    )
    backend = build_backend(lambda _arguments: None)
    runner = CliRunner()
    try:
        for name, path, database in (("cache-a", first, "3"), ("cache-b", second, "8")):
            result = runner.invoke(
                cli,
                ["--json", "profile", "set", name, "--path", str(path), "--host", "cache.local", "--db", database],
                obj=CommandContext(backend, profile_manager=manager),
            )
            assert result.exit_code == 0, result.output

        first_current = runner.invoke(
            cli,
            ["--json", "profile", "current", "--path", str(first)],
            obj=CommandContext(backend, profile_manager=manager),
        )
        second_current = runner.invoke(
            cli,
            ["--json", "profile", "current", "--path", str(second)],
            obj=CommandContext(backend, profile_manager=manager),
        )

        assert json.loads(first_current.output)["data"]["database"] == 3
        assert json.loads(second_current.output)["data"]["database"] == 8
    finally:
        backend.close()
