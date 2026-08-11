"""连接管理工具 — minio_connect / minio_disconnect / minio_status."""

import contextlib
from collections.abc import Callable
from typing import Any

from mcp.types import Tool

from mcp_base.types import ToolResult
from mcp_minio.connection import MinioConnection


def get_definitions() -> list[Tool]:
    return [
        Tool(
            name="minio_connect",
            description="连接到 MinIO, 可指定 endpoint/access_key/secret_key/secure 覆盖默认配置",
            inputSchema={
                "type": "object",
                "properties": {
                    "endpoint": {"type": "string", "description": "MinIO 地址 (默认 localhost:9002)"},
                    "access_key": {"type": "string", "description": "Access Key"},
                    "secret_key": {"type": "string", "description": "Secret Key"},
                    "secure": {"type": "boolean", "description": "使用 TLS (默认 false)"},
                },
            },
        ),
        Tool(
            name="minio_disconnect",
            description="断开当前 MinIO 连接",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="minio_status",
            description="查看 MinIO 连接状态和配置",
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


def build_handlers(conn: MinioConnection) -> dict[str, Callable[[dict[str, Any]], Any]]:
    h = _ConnectionHandlers(conn)
    return {"minio_connect": h.connect, "minio_disconnect": h.disconnect, "minio_status": h.status}


class _ConnectionHandlers:
    def __init__(self, conn: MinioConnection):
        self._conn = conn

    async def connect(self, args: dict[str, Any]) -> ToolResult:
        await self._conn.connect(**args)
        cfg = self._conn.config
        return ToolResult.success(
            message=f"已连接 MinIO {cfg.endpoint}", data={"endpoint": cfg.endpoint},
        )

    async def disconnect(self, _args: dict[str, Any]) -> ToolResult:
        await self._conn.disconnect()
        return ToolResult.success(message="已断开 MinIO 连接")

    async def status(self, _args: dict[str, Any]) -> ToolResult:
        connected = self._conn.is_connected
        data: dict[str, Any] = {"connected": connected, "config": self._conn.config.safe_info()}
        if connected:
            with contextlib.suppress(Exception):
                data["buckets"] = await self._conn.list_buckets()
        return ToolResult.success(message="已连接" if connected else "未连接", data=data)
