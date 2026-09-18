"""MySQL adapter implementing the shared database backend interface."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any, cast

from db_cli_core.async_runner import AsyncRunner
from mcp_base.types import ToolResult
from mcp_mysql.connection import MySQLConnection
from mcp_mysql.tools import build_dispatch
from mysql_cli.config import MySQLConnectionOptions
from mysql_cli.enums import MySQLConnectionCommand

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping

    from db_cli_core.types import Arguments

    MySQLHandler = Callable[[Arguments], Awaitable[ToolResult]]


class MySQLBackend:
    def __init__(
        self,
        options: MySQLConnectionOptions | None = None,
        connection: MySQLConnection | None = None,
        handlers: Mapping[str, MySQLHandler] | None = None,
        async_runner: AsyncRunner | None = None,
    ) -> None:
        self._defaults = options or MySQLConnectionOptions.from_environment()
        self._options = self._defaults
        self._connection = connection or MySQLConnection()
        default_handlers = cast("Mapping[str, MySQLHandler]", build_dispatch(self._connection))
        self._handlers = handlers if handlers is not None else default_handlers
        self._async_runner = async_runner or AsyncRunner()

    @property
    def target_label(self) -> str:
        return self._options.database or "server"

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
        if tool_name == MySQLConnectionCommand.CONNECT.value:
            return self._connect(arguments)
        if tool_name == MySQLConnectionCommand.DISCONNECT.value:
            self._async_runner.run(self._connection.disconnect())
            return ToolResult.success(message="已断开 MySQL 连接")
        if tool_name == MySQLConnectionCommand.STATUS.value:
            return self._status()

        handler = self._handlers.get(tool_name)
        if handler is None:
            return ToolResult.error(f"未知 MySQL 命令: {tool_name}")
        self._ensure_connected()
        result = self._async_runner.run(handler(arguments))
        if tool_name == "mysql_execute" and isinstance(result.data, dict):
            result = replace(result, data={key: value for key, value in result.data.items() if key != "sql"})
        return result

    def switch_target(self, target: str) -> ToolResult:
        database = target.strip()
        if not database:
            return ToolResult.error("MySQL 数据库名不能为空")
        self._options = self._options.apply_overrides(database=database)
        self._async_runner.run(self._connection.connect(**self._options.connection_arguments()))
        return ToolResult.success(message=f"已切换到 MySQL 数据库 {database}")

    def close(self) -> None:
        self._async_runner.run(self._connection.disconnect())
        self._async_runner.close()

    def _connect(self, arguments: Arguments) -> ToolResult:
        self._options = self._options.apply_overrides(**arguments)
        self._async_runner.run(self._connection.connect(**self._options.connection_arguments()))
        return ToolResult.success(message="已连接 MySQL")

    def _status(self) -> ToolResult:
        data: dict[str, Any] = {"connected": self._connection.is_connected, "config": self._options.safe_info()}
        if self._connection.is_connected:
            data["server_info"] = self._async_runner.run(self._connection.get_server_info())
            data["pool_status"] = self._connection.get_pool_status()
        return ToolResult.success(
            message="已连接" if self._connection.is_connected else "未连接",
            data=data,
        )

    def _ensure_connected(self) -> None:
        if not self._connection.is_connected:
            self._async_runner.run(self._connection.connect(**self._options.connection_arguments()))
