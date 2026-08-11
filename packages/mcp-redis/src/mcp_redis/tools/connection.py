"""连接管理工具 — redis_connect / redis_disconnect / redis_status."""

from collections.abc import Callable
from typing import Any

from mcp.types import Tool

from mcp_base.types import ToolResult
from mcp_redis.connection import RedisConnection

# ── 工具定义 ──


def get_definitions() -> list[Tool]:
    return [
        Tool(
            name="redis_connect",
            description="连接到 Redis 服务器, 可指定 host/port/username/password/db 覆盖默认配置",
            inputSchema={
                "type": "object",
                "properties": {
                    "host": {"type": "string", "description": "Redis 主机地址 (默认 localhost)"},
                    "port": {"type": "integer", "description": "Redis 端口 (默认 6379)"},
                    "username": {"type": "string", "description": "用户名 (Redis 6.0+ ACL)"},
                    "password": {"type": "string", "description": "密码"},
                    "db": {"type": "integer", "description": "数据库编号 (默认 0)"},
                },
            },
        ),
        Tool(
            name="redis_disconnect",
            description="断开当前 Redis 连接",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="redis_status",
            description="查看 Redis 连接状态、配置和服务器基本信息",
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


# ── 处理器构建 ──


def build_handlers(conn: RedisConnection) -> dict[str, Callable[[dict[str, Any]], Any]]:
    handlers = _ConnectionHandlers(conn)
    return {
        "redis_connect": handlers.connect,
        "redis_disconnect": handlers.disconnect,
        "redis_status": handlers.status,
    }


class _ConnectionHandlers:
    def __init__(self, conn: RedisConnection):
        self._conn = conn

    async def connect(self, args: dict[str, Any]) -> ToolResult:
        await self._conn.connect(**args)
        cfg = self._conn.config
        return ToolResult.success(
            message=f"已连接 Redis {cfg.host}:{cfg.port}",
            data={"host": cfg.host, "port": cfg.port, "db": cfg.db},
        )

    async def disconnect(self, _args: dict[str, Any]) -> ToolResult:
        await self._conn.disconnect()
        return ToolResult.success(message="已断开 Redis 连接")

    async def status(self, _args: dict[str, Any]) -> ToolResult:
        connected = self._conn.is_connected
        data: dict[str, Any] = {"connected": connected, "config": self._conn.config.safe_info()}
        if connected:
            try:
                data["server"] = await self._conn.server_info("server")
                data["dbsize"] = await self._conn.server_dbsize()
            except Exception:
                pass
        return ToolResult.success(
            message="已连接" if connected else "未连接",
            data=data,
        )
