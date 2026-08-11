"""Bucket 操作工具 — minio_list_buckets / make_bucket / remove_bucket / bucket_exists."""

from collections.abc import Callable
from typing import Any

from mcp.types import Tool

from mcp_base.types import ToolResult
from mcp_minio.connection import MinioConnection


def get_definitions() -> list[Tool]:
    return [
        Tool(
            name="minio_list_buckets",
            description="列出所有 Bucket 及其创建时间",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="minio_bucket_exists",
            description="检查指定 Bucket 是否存在",
            inputSchema={
                "type": "object",
                "properties": {"name": {"type": "string", "description": "Bucket 名称"}},
                "required": ["name"],
            },
        ),
        Tool(
            name="minio_make_bucket",
            description="创建新 Bucket (Bucket 名必须全局唯一且符合命名规范)",
            inputSchema={
                "type": "object",
                "properties": {"name": {"type": "string", "description": "Bucket 名称"}},
                "required": ["name"],
            },
        ),
        Tool(
            name="minio_remove_bucket",
            description="删除空 Bucket (仅当 Bucket 为空时才能删除)",
            inputSchema={
                "type": "object",
                "properties": {"name": {"type": "string", "description": "Bucket 名称"}},
                "required": ["name"],
            },
        ),
    ]


def build_handlers(conn: MinioConnection) -> dict[str, Callable[[dict[str, Any]], Any]]:
    h = _BucketHandlers(conn)
    return {
        "minio_list_buckets": h.list_buckets,
        "minio_bucket_exists": h.bucket_exists,
        "minio_make_bucket": h.make_bucket,
        "minio_remove_bucket": h.remove_bucket,
    }


class _BucketHandlers:
    def __init__(self, conn: MinioConnection):
        self._conn = conn

    async def list_buckets(self, _args: dict[str, Any]) -> ToolResult:
        buckets = await self._conn.list_buckets()
        return ToolResult.success(data={"buckets": buckets, "count": len(buckets)})

    async def bucket_exists(self, args: dict[str, Any]) -> ToolResult:
        name = args["name"]
        ok = await self._conn.bucket_exists(name)
        return ToolResult.success(data={"name": name, "exists": ok})

    async def make_bucket(self, args: dict[str, Any]) -> ToolResult:
        name = args["name"]
        await self._conn.make_bucket(name)
        return ToolResult.success(data={"name": name})

    async def remove_bucket(self, args: dict[str, Any]) -> ToolResult:
        name = args["name"]
        await self._conn.remove_bucket(name)
        return ToolResult.success(data={"name": name})
