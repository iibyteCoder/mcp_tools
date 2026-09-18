"""Redis adapter implementing the shared database backend interface."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any, cast

from db_cli_core.async_runner import AsyncRunner
from mcp_base.types import ToolResult
from mcp_redis.connection import RedisConnection
from mcp_redis.tools import build_dispatch
from redis_cli.config import RedisConnectionOptions
from redis_cli.enums import RedisConnectionCommand
from redis_cli.read_operations import inspect_key, scan_page

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping

    from db_cli_core.types import Arguments

    RedisHandler = Callable[[Arguments], Awaitable[ToolResult]]


class RedisBackend:
    def __init__(
        self,
        options: RedisConnectionOptions | None = None,
        connection: RedisConnection | None = None,
        handlers: Mapping[str, RedisHandler] | None = None,
        async_runner: AsyncRunner | None = None,
    ) -> None:
        self._defaults = options or RedisConnectionOptions.from_environment()
        self._options = self._defaults
        self._connection = connection or RedisConnection()
        default_handlers = cast("Mapping[str, RedisHandler]", build_dispatch(self._connection))
        default_handlers = dict(default_handlers) | {"redis_pipeline": self._pipeline}
        self._handlers = handlers if handlers is not None else default_handlers
        self._async_runner = async_runner or AsyncRunner()

    @property
    def target_label(self) -> str:
        return f"db{self._options.database}"

    @property
    def connection_info(self) -> dict[str, Any]:
        return self._options.safe_info()

    def configure(self, url: str | None = None, **overrides: Any) -> None:
        options = self._options.apply_url(url) if url else self._options
        updated = options.apply_overrides(**overrides)
        if updated != self._options and self._connection.is_connected:
            self._async_runner.run(self._connection.disconnect())
        self._options = updated

    def build_profile(self, url: str | None = None, **overrides: Any) -> dict[str, Any]:
        options = self._options.apply_url(url) if url else self._options
        return options.apply_overrides(**overrides).profile_settings()

    def reset_configuration(self) -> None:
        if self._options != self._defaults and self._connection.is_connected:
            self._async_runner.run(self._connection.disconnect())
        self._options = self._defaults

    def invoke(self, tool_name: str, arguments: Arguments) -> ToolResult:
        if tool_name == RedisConnectionCommand.CONNECT.value:
            return self._connect(arguments)
        if tool_name == RedisConnectionCommand.DISCONNECT.value:
            self._async_runner.run(self._connection.disconnect())
            return ToolResult.success(message="已断开 Redis 连接")
        if tool_name == RedisConnectionCommand.STATUS.value:
            return ToolResult.success(
                message="已连接" if self._connection.is_connected else "未连接",
                data={"connected": self._connection.is_connected, "config": self._options.safe_info()},
            )

        handler = self._handlers.get(tool_name)
        if handler is None:
            return ToolResult.error(f"未知 Redis 命令: {tool_name}")
        self._ensure_connected()
        return self._async_runner.run(handler(arguments))

    def switch_target(self, target: str) -> ToolResult:
        try:
            database = int(target)
        except ValueError:
            return ToolResult.error(f"Redis 数据库必须是非负整数: {target}")
        if database < 0:
            return ToolResult.error(f"Redis 数据库必须是非负整数: {target}")
        self._options = self._options.apply_overrides(database=database)
        self._async_runner.run(self._connection.connect(**self._options.connection_arguments()))
        return ToolResult.success(message=f"已切换到 Redis DB {database}")

    async def _pipeline(self, arguments: Arguments) -> ToolResult:
        commands = arguments["commands"]
        if (
            not isinstance(commands, list)
            or not commands
            or any(
                not isinstance(command, list) or not command or any(not isinstance(arg, str) for arg in command)
                for command in commands
            )
        ):
            raise ValueError("commands 必须是非空字符串数组组成的非空数组")
        results = await self._connection.pipeline_execute(commands)
        return ToolResult.success(data={"results": results})

    def read(self, operation: str, **arguments: Any) -> ToolResult:
        self._ensure_connected()
        if operation == "inspect":
            data = self._async_runner.run(inspect_key(self._connection.client, **arguments))
        else:
            identity = {
                key: value
                for key, value in self._options.safe_info().items()
                if key not in {"password", "connection_timeout"}
            }
            target = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
            data = self._async_runner.run(scan_page(self._connection.client, target=target, **arguments))
        return ToolResult.success(data=data)

    def close(self) -> None:
        self._async_runner.run(self._connection.disconnect())
        self._async_runner.close()

    def _connect(self, arguments: Arguments) -> ToolResult:
        normalized = {"database" if name == "db" else name: value for name, value in arguments.items()}
        self._options = self._options.apply_overrides(**normalized)
        self._async_runner.run(self._connection.connect(**self._options.connection_arguments()))
        return ToolResult.success(message="已连接 Redis")

    def _ensure_connected(self) -> None:
        if not self._connection.is_connected:
            self._async_runner.run(self._connection.connect(**self._options.connection_arguments()))
