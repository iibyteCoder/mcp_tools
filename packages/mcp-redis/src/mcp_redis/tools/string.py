"""String 操作工具 — GET/SET/MGET/MSET/INCR/APPEND/STRLEN."""

from collections.abc import Callable
from typing import Any

from mcp.types import Tool

from mcp_base.types import ToolResult
from mcp_redis.connection import RedisConnection


def get_definitions() -> list[Tool]:
    return [
        Tool(
            name="redis_get",
            description="获取字符串 key 的值, key 不存在返回 null",
            inputSchema={
                "type": "object",
                "properties": {"key": {"type": "string", "description": "Redis key"}},
                "required": ["key"],
            },
        ),
        Tool(
            name="redis_set",
            description="设置字符串 key 的值, 可选过期秒数、仅当不存在(nx)或仅当存在(xx)时写入",
            inputSchema={
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "Redis key"},
                    "value": {"type": "string", "description": "值"},
                    "ex": {"type": "integer", "description": "过期秒数, 不填则永久"},
                    "nx": {"type": "boolean", "description": "仅 key 不存在时写入"},
                    "xx": {"type": "boolean", "description": "仅 key 存在时写入"},
                },
                "required": ["key", "value"],
            },
        ),
        Tool(
            name="redis_mget",
            description="批量获取多个 key 的字符串值, 不存在的 key 返回 null",
            inputSchema={
                "type": "object",
                "properties": {"keys": {"type": "array", "items": {"type": "string"}, "description": "key 列表"}},
                "required": ["keys"],
            },
        ),
        Tool(
            name="redis_mset",
            description="批量设置多个 key-value",
            inputSchema={
                "type": "object",
                "properties": {"mapping": {"type": "object", "description": "{key: value, ...} 映射"}},
                "required": ["mapping"],
            },
        ),
        Tool(
            name="redis_incr",
            description="将 key 的数字值增加 amount(默认为 1,传负数递减),返回新值",
            inputSchema={
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "Redis key"},
                    "amount": {"type": "integer", "description": "增量, 默认 1, 可为负数"},
                },
                "required": ["key"],
            },
        ),
        Tool(
            name="redis_append",
            description="向 key 字符串值末尾追加内容,返回追加后总长度",
            inputSchema={
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "Redis key"},
                    "value": {"type": "string", "description": "追加的字符串"},
                },
                "required": ["key", "value"],
            },
        ),
        Tool(
            name="redis_strlen",
            description="获取 key 的字符串值长度",
            inputSchema={
                "type": "object",
                "properties": {"key": {"type": "string", "description": "Redis key"}},
                "required": ["key"],
            },
        ),
    ]


def build_handlers(conn: RedisConnection) -> dict[str, Callable[[dict[str, Any]], Any]]:
    h = _StringHandlers(conn)
    return {
        "redis_get": h.get,
        "redis_set": h.set,
        "redis_mget": h.mget,
        "redis_mset": h.mset,
        "redis_incr": h.incr,
        "redis_append": h.append,
        "redis_strlen": h.strlen,
    }


class _StringHandlers:
    def __init__(self, conn: RedisConnection):
        self._conn = conn

    async def get(self, args: dict[str, Any]) -> ToolResult:
        key = args["key"]
        val = await self._conn.string_get(key)
        return ToolResult.success(data={"key": key, "value": val})

    async def set(self, args: dict[str, Any]) -> ToolResult:
        key, value = args["key"], args["value"]
        kwargs = {}
        if args.get("ex") is not None:
            kwargs["ex"] = int(args["ex"])
        if args.get("nx"):
            kwargs["nx"] = True
        if args.get("xx"):
            kwargs["xx"] = True
        ok = await self._conn.string_set(key, value, **kwargs)
        return ToolResult.success(data={"key": key, "ok": ok, **kwargs})

    async def mget(self, args: dict[str, Any]) -> ToolResult:
        keys: list[str] = args["keys"]
        vals = await self._conn.string_mget(*keys)
        result = dict(zip(keys, vals, strict=True))
        hit = sum(1 for v in vals if v is not None)
        return ToolResult.success(data={"values": result, "hit": hit, "miss": len(keys) - hit})

    async def mset(self, args: dict[str, Any]) -> ToolResult:
        mapping: dict[str, str] = args["mapping"]
        await self._conn.string_mset(mapping)
        return ToolResult.success(data={"count": len(mapping)})

    async def incr(self, args: dict[str, Any]) -> ToolResult:
        key = args["key"]
        amount = args.get("amount", 1)
        new_val = await self._conn.string_incr(key, amount)
        return ToolResult.success(data={"key": key, "amount": amount, "result": new_val})

    async def append(self, args: dict[str, Any]) -> ToolResult:
        key, value = args["key"], args["value"]
        new_len = await self._conn.string_append(key, value)
        return ToolResult.success(data={"key": key, "appended": len(value), "total_len": new_len})

    async def strlen(self, args: dict[str, Any]) -> ToolResult:
        key = args["key"]
        n = await self._conn.string_strlen(key)
        return ToolResult.success(data={"key": key, "length": n})
