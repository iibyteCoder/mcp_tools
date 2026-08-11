"""连接管理工具 — mysql_connect / mysql_disconnect / mysql_status."""

from collections.abc import Callable
from typing import Any

from mcp.types import Tool

from mcp_base.types import ToolResult
from mcp_mysql.connection import MySQLConnection


def get_definitions() -> list[Tool]:
    return [
        Tool(
            name="mysql_connect",
            description="连接到 MySQL, 可指定 host/port/user/password/database 覆盖默认配置",
            inputSchema={
                "type": "object",
                "properties": {
                    "host": {"type": "string", "description": "MySQL 主机地址 (默认 localhost)"},
                    "port": {"type": "integer", "description": "端口 (默认 3306)"},
                    "user": {"type": "string", "description": "用户名 (默认 root)"},
                    "password": {"type": "string", "description": "密码"},
                    "database": {"type": "string", "description": "数据库名"},
                },
            },
        ),
        Tool(
            name="mysql_disconnect",
            description="断开当前 MySQL 连接",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="mysql_status",
            description="查看 MySQL 连接状态、服务器版本和连接池信息",
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


def build_handlers(conn: MySQLConnection) -> dict[str, Callable[[dict[str, Any]], Any]]:
    handlers = _ConnectionHandlers(conn)
    return {
        "mysql_connect": handlers.connect,
        "mysql_disconnect": handlers.disconnect,
        "mysql_status": handlers.status,
    }


class _ConnectionHandlers:
    def __init__(self, conn: MySQLConnection):
        self._conn = conn

    async def connect(self, args: dict[str, Any]) -> ToolResult:
        await self._conn.connect(**args)
        cfg = self._conn.config
        return ToolResult.success(
            message=f"已连接 MySQL {cfg.host}:{cfg.port}",
            data={"host": cfg.host, "port": cfg.port, "database": cfg.database or "(none)"},
        )

    async def disconnect(self, _args: dict[str, Any]) -> ToolResult:
        await self._conn.disconnect()
        return ToolResult.success(message="已断开 MySQL 连接")

    async def status(self, _args: dict[str, Any]) -> ToolResult:
        connected = self._conn.is_connected
        data: dict[str, Any] = {"connected": connected, "config": self._conn.config.safe_info()}
        if connected:
            try:
                data["server_info"] = await self._conn.get_server_info()
                data["pool_status"] = self._conn.get_pool_status()
            except Exception:
                pass
        return ToolResult.success(message="已连接" if connected else "未连接", data=data)
