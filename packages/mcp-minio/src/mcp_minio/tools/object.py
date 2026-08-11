"""Object 操作工具 — put/get/remove/list/stat/copy + presigned URL."""

from collections.abc import Callable
from typing import Any

from mcp.types import Tool

from mcp_base.types import ToolResult
from mcp_minio.connection import MinioConnection


def get_definitions() -> list[Tool]:
    return [
        Tool(
            name="minio_put_object",
            description="上传对象到 Bucket, data 为 base64 编码的文件内容",
            inputSchema={
                "type": "object",
                "properties": {
                    "bucket": {"type": "string", "description": "Bucket 名称"},
                    "name": {"type": "string", "description": "对象名/路径"},
                    "data": {"type": "string", "description": "文件内容的 base64 编码字符串"},
                    "content_type": {"type": "string", "description": "MIME 类型, 默认 application/octet-stream"},
                },
                "required": ["bucket", "name", "data"],
            },
        ),
        Tool(
            name="minio_get_object",
            description="下载对象, 返回 base64 编码的内容和元信息",
            inputSchema={
                "type": "object",
                "properties": {
                    "bucket": {"type": "string", "description": "Bucket 名称"},
                    "name": {"type": "string", "description": "对象名/路径"},
                },
                "required": ["bucket", "name"],
            },
        ),
        Tool(
            name="minio_remove_object",
            description="删除指定对象",
            inputSchema={
                "type": "object",
                "properties": {
                    "bucket": {"type": "string", "description": "Bucket 名称"},
                    "name": {"type": "string", "description": "对象名/路径"},
                },
                "required": ["bucket", "name"],
            },
        ),
        Tool(
            name="minio_list_objects",
            description="列出 Bucket 中的对象, 支持按前缀过滤和递归子目录",
            inputSchema={
                "type": "object",
                "properties": {
                    "bucket": {"type": "string", "description": "Bucket 名称"},
                    "prefix": {"type": "string", "description": "前缀过滤 (如 course-parse/), 默认全部"},
                    "recursive": {"type": "boolean", "description": "是否递归子目录, 默认 false"},
                    "max_keys": {"type": "integer", "description": "最大返回数, 默认 100"},
                },
                "required": ["bucket"],
            },
        ),
        Tool(
            name="minio_stat_object",
            description="获取对象元信息(大小/类型/ETag/修改时间/自定义元数据), 对象不存在返回 null",
            inputSchema={
                "type": "object",
                "properties": {
                    "bucket": {"type": "string", "description": "Bucket 名称"},
                    "name": {"type": "string", "description": "对象名/路径"},
                },
                "required": ["bucket", "name"],
            },
        ),
        Tool(
            name="minio_copy_object",
            description="复制对象到同/不同 Bucket",
            inputSchema={
                "type": "object",
                "properties": {
                    "src_bucket": {"type": "string", "description": "源 Bucket"},
                    "src_name": {"type": "string", "description": "源对象名"},
                    "dst_bucket": {"type": "string", "description": "目标 Bucket"},
                    "dst_name": {"type": "string", "description": "目标对象名"},
                },
                "required": ["src_bucket", "src_name", "dst_bucket", "dst_name"],
            },
        ),
        Tool(
            name="minio_presigned_get_url",
            description="生成对象预签名下载 URL, 可设置过期秒数(默认 3600)",
            inputSchema={
                "type": "object",
                "properties": {
                    "bucket": {"type": "string", "description": "Bucket 名称"},
                    "name": {"type": "string", "description": "对象名/路径"},
                    "expires": {"type": "integer", "description": "URL 有效秒数, 默认 3600"},
                },
                "required": ["bucket", "name"],
            },
        ),
        Tool(
            name="minio_presigned_put_url",
            description="生成对象预签名上传 URL, 可设置过期秒数(默认 3600)",
            inputSchema={
                "type": "object",
                "properties": {
                    "bucket": {"type": "string", "description": "Bucket 名称"},
                    "name": {"type": "string", "description": "对象名/路径"},
                    "expires": {"type": "integer", "description": "URL 有效秒数, 默认 3600"},
                },
                "required": ["bucket", "name"],
            },
        ),
    ]


def build_handlers(conn: MinioConnection) -> dict[str, Callable[[dict[str, Any]], Any]]:
    h = _ObjectHandlers(conn)
    return {
        "minio_put_object": h.put_object,
        "minio_get_object": h.get_object,
        "minio_remove_object": h.remove_object,
        "minio_list_objects": h.list_objects,
        "minio_stat_object": h.stat_object,
        "minio_copy_object": h.copy_object,
        "minio_presigned_get_url": h.presigned_get_url,
        "minio_presigned_put_url": h.presigned_put_url,
    }


class _ObjectHandlers:
    def __init__(self, conn: MinioConnection):
        self._conn = conn

    async def put_object(self, args: dict[str, Any]) -> ToolResult:
        import base64
        bucket, name = args["bucket"], args["name"]
        data = base64.b64decode(args["data"])
        ct = args.get("content_type", "application/octet-stream")
        await self._conn.put_object(bucket, name, data, content_type=ct)
        return ToolResult.success(data={"bucket": bucket, "name": name, "size": len(data)})

    async def get_object(self, args: dict[str, Any]) -> ToolResult:
        import base64
        bucket, name = args["bucket"], args["name"]
        data = await self._conn.get_object(bucket, name)
        if data is None:
            return ToolResult.success(data={"bucket": bucket, "name": name, "data": None, "exists": False})
        stat = await self._conn.stat_object(bucket, name)
        return ToolResult.success(data={
            "bucket": bucket, "name": name,
            "data": base64.b64encode(data).decode("utf-8"),
            "size": len(data), "stat": stat,
        })

    async def remove_object(self, args: dict[str, Any]) -> ToolResult:
        bucket, name = args["bucket"], args["name"]
        await self._conn.remove_object(bucket, name)
        return ToolResult.success(data={"bucket": bucket, "name": name})

    async def list_objects(self, args: dict[str, Any]) -> ToolResult:
        bucket = args["bucket"]
        prefix = args.get("prefix", "")
        recursive = args.get("recursive", False)
        max_keys = args.get("max_keys", 100)
        objs = await self._conn.list_objects(bucket, prefix=prefix, recursive=recursive, max_keys=max_keys)
        return ToolResult.success(data={"bucket": bucket, "prefix": prefix, "objects": objs, "count": len(objs)})

    async def stat_object(self, args: dict[str, Any]) -> ToolResult:
        bucket, name = args["bucket"], args["name"]
        stat = await self._conn.stat_object(bucket, name)
        return ToolResult.success(data={"bucket": bucket, "name": name, "exists": stat is not None, "stat": stat})

    async def copy_object(self, args: dict[str, Any]) -> ToolResult:
        sb, sn, db, dn = args["src_bucket"], args["src_name"], args["dst_bucket"], args["dst_name"]
        await self._conn.copy_object(sb, sn, db, dn)
        return ToolResult.success(data={"src": f"{sb}/{sn}", "dst": f"{db}/{dn}"})

    async def presigned_get_url(self, args: dict[str, Any]) -> ToolResult:
        bucket, name = args["bucket"], args["name"]
        expires = args.get("expires", 3600)
        url = await self._conn.presigned_get_url(bucket, name, expires=expires)
        return ToolResult.success(data={"bucket": bucket, "name": name, "url": url, "expires": expires})

    async def presigned_put_url(self, args: dict[str, Any]) -> ToolResult:
        bucket, name = args["bucket"], args["name"]
        expires = args.get("expires", 3600)
        url = await self._conn.presigned_put_url(bucket, name, expires=expires)
        return ToolResult.success(data={"bucket": bucket, "name": name, "url": url, "expires": expires})
