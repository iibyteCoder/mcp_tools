"""List 操作工具 — LPUSH/RPUSH/LPOP/RPOP/LRANGE/LLEN/LINDEX/LTRIM."""

from collections.abc import Callable
from typing import Any

from mcp.types import Tool

from mcp_base.types import ToolResult
from mcp_redis.connection import RedisConnection


def get_definitions() -> list[Tool]:
    return [
        Tool(
            name="redis_lpush",
            description="向列表头部插入一个或多个元素,返回插入后列表长度",
            inputSchema={
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "Redis key"},
                    "values": {"type": "array", "items": {"type": "string"}, "description": "插入的值列表"},
                },
                "required": ["key", "values"],
            },
        ),
        Tool(
            name="redis_rpush",
            description="向列表尾部追加一个或多个元素,返回追加后列表长度",
            inputSchema={
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "Redis key"},
                    "values": {"type": "array", "items": {"type": "string"}, "description": "追加的值列表"},
                },
                "required": ["key", "values"],
            },
        ),
        Tool(
            name="redis_lpop",
            description="从列表头部弹出 count 个元素(默认 1),列表为空返回空数组",
            inputSchema={
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "Redis key"},
                    "count": {"type": "integer", "description": "弹出数量, 默认 1"},
                },
                "required": ["key"],
            },
        ),
        Tool(
            name="redis_rpop",
            description="从列表尾部弹出 count 个元素(默认 1),列表为空返回空数组",
            inputSchema={
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "Redis key"},
                    "count": {"type": "integer", "description": "弹出数量, 默认 1"},
                },
                "required": ["key"],
            },
        ),
        Tool(
            name="redis_lrange",
            description="获取列表 [start, stop] 范围的元素.0=第一个, -1=最后一个",
            inputSchema={
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "Redis key"},
                    "start": {"type": "integer", "description": "起始索引, 0=第一个"},
                    "stop": {"type": "integer", "description": "结束索引, -1=最后一个"},
                },
                "required": ["key", "start", "stop"],
            },
        ),
        Tool(
            name="redis_llen",
            description="获取列表长度",
            inputSchema={
                "type": "object",
                "properties": {"key": {"type": "string", "description": "Redis key"}},
                "required": ["key"],
            },
        ),
        Tool(
            name="redis_lindex",
            description="获取列表索引位置的元素, 0=第一个, 负数从尾部算, 越界返回 null",
            inputSchema={
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "Redis key"},
                    "index": {"type": "integer", "description": "索引位置"},
                },
                "required": ["key", "index"],
            },
        ),
        Tool(
            name="redis_ltrim",
            description="裁剪列表, 只保留 [start, stop] 范围的元素",
            inputSchema={
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "Redis key"},
                    "start": {"type": "integer", "description": "起始索引"},
                    "stop": {"type": "integer", "description": "结束索引, -1=最后一个"},
                },
                "required": ["key", "start", "stop"],
            },
        ),
    ]


def build_handlers(conn: RedisConnection) -> dict[str, Callable[[dict[str, Any]], Any]]:
    h = _ListHandlers(conn)
    return {
        "redis_lpush": h.lpush,
        "redis_rpush": h.rpush,
        "redis_lpop": h.lpop,
        "redis_rpop": h.rpop,
        "redis_lrange": h.lrange,
        "redis_llen": h.llen,
        "redis_lindex": h.lindex,
        "redis_ltrim": h.ltrim,
    }


class _ListHandlers:
    def __init__(self, conn: RedisConnection):
        self._conn = conn

    async def lpush(self, args: dict[str, Any]) -> ToolResult:
        key = args["key"]
        vals: list[str] = args["values"]
        length = await self._conn.list_push(key, *vals, left=True)
        return ToolResult.success(data={"key": key, "added": len(vals), "length": length})

    async def rpush(self, args: dict[str, Any]) -> ToolResult:
        key = args["key"]
        vals: list[str] = args["values"]
        length = await self._conn.list_push(key, *vals, left=False)
        return ToolResult.success(data={"key": key, "added": len(vals), "length": length})

    async def _pop(self, args: dict[str, Any], left: bool) -> ToolResult:
        key = args["key"]
        count = args.get("count", 1)
        result = await self._conn.list_pop(key, left=left, count=count)
        values = []
        if result is not None:
            values = list(result) if isinstance(result, list) else [result]
        return ToolResult.success(data={"key": key, "values": values, "count": len(values)})

    async def lpop(self, args: dict[str, Any]) -> ToolResult:
        return await self._pop(args, left=True)

    async def rpop(self, args: dict[str, Any]) -> ToolResult:
        return await self._pop(args, left=False)

    async def lrange(self, args: dict[str, Any]) -> ToolResult:
        key, start, stop = args["key"], args["start"], args["stop"]
        vals = await self._conn.list_range(key, start, stop)
        return ToolResult.success(data={"key": key, "start": start, "stop": stop, "values": vals, "count": len(vals)})

    async def llen(self, args: dict[str, Any]) -> ToolResult:
        key = args["key"]
        n = await self._conn.list_length(key)
        return ToolResult.success(data={"key": key, "length": n})

    async def lindex(self, args: dict[str, Any]) -> ToolResult:
        key, idx = args["key"], args["index"]
        val = await self._conn.list_index(key, idx)
        return ToolResult.success(data={"key": key, "index": idx, "value": val})

    async def ltrim(self, args: dict[str, Any]) -> ToolResult:
        key, start, stop = args["key"], args["start"], args["stop"]
        await self._conn.list_trim(key, start, stop)
        return ToolResult.success(data={"key": key, "start": start, "stop": stop})
