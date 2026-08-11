"""连接管理工具 — neo4j_connect / neo4j_disconnect / neo4j_status."""

from collections.abc import Callable
from typing import Any

from mcp.types import Tool

from mcp_base.types import ToolResult
from mcp_neo4j.connection import Neo4jConnection


def get_definitions() -> list[Tool]:
    return [
        Tool(
            name="neo4j_connect",
            description="连接到 Neo4j, 可指定 uri/user/password/database 覆盖默认配置",
            inputSchema={
                "type": "object",
                "properties": {
                    "uri": {"type": "string", "description": "Bolt URI (默认 bolt://localhost:7687)"},
                    "user": {"type": "string", "description": "用户名 (默认 neo4j)"},
                    "password": {"type": "string", "description": "密码"},
                    "database": {"type": "string", "description": "数据库名 (默认 neo4j)"},
                },
            },
        ),
        Tool(
            name="neo4j_disconnect",
            description="断开当前 Neo4j 连接",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="neo4j_status",
            description="查看 Neo4j 连接状态、服务器版本和连接池信息",
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


def build_handlers(conn: Neo4jConnection) -> dict[str, Callable[[dict[str, Any]], Any]]:
    handlers = _ConnectionHandlers(conn)
    return {
        "neo4j_connect": handlers.connect,
        "neo4j_disconnect": handlers.disconnect,
        "neo4j_status": handlers.status,
    }


class _ConnectionHandlers:
    def __init__(self, conn: Neo4jConnection):
        self._conn = conn

    async def connect(self, args: dict[str, Any]) -> ToolResult:
        await self._conn.connect(**args)
        cfg = self._conn.config
        return ToolResult.success(
            message=f"已连接 Neo4j {cfg.uri}",
            data={"uri": cfg.uri, "database": cfg.database},
        )

    async def disconnect(self, _args: dict[str, Any]) -> ToolResult:
        await self._conn.disconnect()
        return ToolResult.success(message="已断开 Neo4j 连接")

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
