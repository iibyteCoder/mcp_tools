"""Hash 操作工具 — HGET/HSET/HGETALL/HDEL/HEXISTS/HKEYS/HVALS/HLEN."""

from collections.abc import Callable
from typing import Any

from mcp.types import Tool

from mcp_base.types import ToolResult
from mcp_redis.connection import RedisConnection


def get_definitions() -> list[Tool]:
    return [
        Tool(
            name="redis_hget",
            description="获取 hash 中指定 field 的值, 不存在返回 null",
            inputSchema={
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "Redis key"},
                    "field": {"type": "string", "description": "字段名"},
                },
                "required": ["key", "field"],
            },
        ),
        Tool(
            name="redis_hset",
            description="设置 hash 中一个或多个 field 的值, 返回新增字段数",
            inputSchema={
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "Redis key"},
                    "mapping": {"type": "object", "description": "{field: value, ...} 映射"},
                },
                "required": ["key", "mapping"],
            },
        ),
        Tool(
            name="redis_hgetall",
            description="获取 hash 的全部 field 和 value",
            inputSchema={
                "type": "object",
                "properties": {"key": {"type": "string", "description": "Redis key"}},
                "required": ["key"],
            },
        ),
        Tool(
            name="redis_hdel",
            description="删除 hash 中一个或多个 field, 返回实际删除数量",
            inputSchema={
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "Redis key"},
                    "fields": {"type": "array", "items": {"type": "string"}, "description": "要删除的字段名列表"},
                },
                "required": ["key", "fields"],
            },
        ),
        Tool(
            name="redis_hexists",
            description="检查 hash 中指定 field 是否存在",
            inputSchema={
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "Redis key"},
                    "field": {"type": "string", "description": "字段名"},
                },
                "required": ["key", "field"],
            },
        ),
        Tool(
            name="redis_hkeys",
            description="获取 hash 的全部 field 名",
            inputSchema={
                "type": "object",
                "properties": {"key": {"type": "string", "description": "Redis key"}},
                "required": ["key"],
            },
        ),
        Tool(
            name="redis_hvals",
            description="获取 hash 的全部 value",
            inputSchema={
                "type": "object",
                "properties": {"key": {"type": "string", "description": "Redis key"}},
                "required": ["key"],
            },
        ),
        Tool(
            name="redis_hlen",
            description="获取 hash 的 field 数量",
            inputSchema={
                "type": "object",
                "properties": {"key": {"type": "string", "description": "Redis key"}},
                "required": ["key"],
            },
        ),
    ]


def build_handlers(conn: RedisConnection) -> dict[str, Callable[[dict[str, Any]], Any]]:
    h = _HashHandlers(conn)
    return {
        "redis_hget": h.hget,
        "redis_hset": h.hset,
        "redis_hgetall": h.hgetall,
        "redis_hdel": h.hdel,
        "redis_hexists": h.hexists,
        "redis_hkeys": h.hkeys,
        "redis_hvals": h.hvals,
        "redis_hlen": h.hlen,
    }


class _HashHandlers:
    def __init__(self, conn: RedisConnection):
        self._conn = conn

    async def hget(self, args: dict[str, Any]) -> ToolResult:
        key, field = args["key"], args["field"]
        val = await self._conn.hash_get(key, field)
        return ToolResult.success(data={"key": key, "field": field, "value": val})

    async def hset(self, args: dict[str, Any]) -> ToolResult:
        key = args["key"]
        mapping: dict[str, str] = args["mapping"]
        added = await self._conn.hash_set(key, mapping)
        return ToolResult.success(data={"key": key, "new_fields": added, "count": len(mapping)})

    async def hgetall(self, args: dict[str, Any]) -> ToolResult:
        key = args["key"]
        data = await self._conn.hash_get_all(key)
        return ToolResult.success(data={"key": key, "fields": data, "count": len(data)})

    async def hdel(self, args: dict[str, Any]) -> ToolResult:
        key = args["key"]
        fields: list[str] = args["fields"]
        n = await self._conn.hash_delete(key, *fields)
        return ToolResult.success(data={"key": key, "requested": len(fields), "deleted": n})

    async def hexists(self, args: dict[str, Any]) -> ToolResult:
        key, field = args["key"], args["field"]
        ok = await self._conn.hash_exists(key, field)
        return ToolResult.success(data={"key": key, "field": field, "exists": ok})

    async def hkeys(self, args: dict[str, Any]) -> ToolResult:
        key = args["key"]
        ks = await self._conn.hash_keys(key)
        return ToolResult.success(data={"key": key, "fields": ks, "count": len(ks)})

    async def hvals(self, args: dict[str, Any]) -> ToolResult:
        key = args["key"]
        vs = await self._conn.hash_values(key)
        return ToolResult.success(data={"key": key, "values": vs, "count": len(vs)})

    async def hlen(self, args: dict[str, Any]) -> ToolResult:
        key = args["key"]
        n = await self._conn.hash_length(key)
        return ToolResult.success(data={"key": key, "length": n})
