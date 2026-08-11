"""Set + Sorted Set 工具 — 集合与有序集合的 CRUD 操作."""

from collections.abc import Callable
from typing import Any

from mcp.types import Tool

from mcp_base.types import ToolResult
from mcp_redis.connection import RedisConnection


def get_definitions() -> list[Tool]:
    return [
        # ── Set ──
        Tool(
            name="redis_sadd",
            description="向集合添加一个或多个成员, 返回新增成员数",
            inputSchema={
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "Redis key"},
                    "members": {"type": "array", "items": {"type": "string"}, "description": "要添加的成员"},
                },
                "required": ["key", "members"],
            },
        ),
        Tool(
            name="redis_srem",
            description="从集合移除一个或多个成员, 返回实际移除数",
            inputSchema={
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "Redis key"},
                    "members": {"type": "array", "items": {"type": "string"}, "description": "要移除的成员"},
                },
                "required": ["key", "members"],
            },
        ),
        Tool(
            name="redis_smembers",
            description="获取集合的全部成员",
            inputSchema={
                "type": "object",
                "properties": {"key": {"type": "string", "description": "Redis key"}},
                "required": ["key"],
            },
        ),
        Tool(
            name="redis_scard",
            description="获取集合的成员数量",
            inputSchema={
                "type": "object",
                "properties": {"key": {"type": "string", "description": "Redis key"}},
                "required": ["key"],
            },
        ),
        Tool(
            name="redis_sismember",
            description="判断 member 是否为集合的成员",
            inputSchema={
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "Redis key"},
                    "member": {"type": "string", "description": "待检查的值"},
                },
                "required": ["key", "member"],
            },
        ),
        # ── Sorted Set ──
        Tool(
            name="redis_zadd",
            description="向有序集合添加成员及其 score, 返回新增成员数",
            inputSchema={
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "Redis key"},
                    "mapping": {"type": "object", "description": "{member: score, ...} 映射, score 为数字"},
                },
                "required": ["key", "mapping"],
            },
        ),
        Tool(
            name="redis_zrem",
            description="从有序集合移除一个或多个成员, 返回实际移除数",
            inputSchema={
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "Redis key"},
                    "members": {"type": "array", "items": {"type": "string"}, "description": "要移除的成员"},
                },
                "required": ["key", "members"],
            },
        ),
        Tool(
            name="redis_zrange",
            description="获取有序集合 [start, stop] 范围的成员(按 score 升序)",
            inputSchema={
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "Redis key"},
                    "start": {"type": "integer", "description": "起始索引, 0=第一个"},
                    "stop": {"type": "integer", "description": "结束索引, -1=最后一个"},
                    "with_scores": {"type": "boolean", "description": "是否同时返回 score, 默认 false"},
                },
                "required": ["key", "start", "stop"],
            },
        ),
        Tool(
            name="redis_zrevrange",
            description="获取有序集合 [start, stop] 范围的成员(按 score 降序)",
            inputSchema={
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "Redis key"},
                    "start": {"type": "integer", "description": "起始索引, 0=第一个"},
                    "stop": {"type": "integer", "description": "结束索引, -1=最后一个"},
                    "with_scores": {"type": "boolean", "description": "是否同时返回 score, 默认 false"},
                },
                "required": ["key", "start", "stop"],
            },
        ),
        Tool(
            name="redis_zcard",
            description="获取有序集合的成员数量",
            inputSchema={
                "type": "object",
                "properties": {"key": {"type": "string", "description": "Redis key"}},
                "required": ["key"],
            },
        ),
        Tool(
            name="redis_zscore",
            description="获取有序集合中成员的 score, 成员不存在返回 null",
            inputSchema={
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "Redis key"},
                    "member": {"type": "string", "description": "成员名"},
                },
                "required": ["key", "member"],
            },
        ),
        Tool(
            name="redis_zrank",
            description="获取成员在有序集合中的升序排名(0=score 最小)",
            inputSchema={
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "Redis key"},
                    "member": {"type": "string", "description": "成员名"},
                },
                "required": ["key", "member"],
            },
        ),
        Tool(
            name="redis_zrevrank",
            description="获取成员在有序集合中的降序排名(0=score 最大)",
            inputSchema={
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "Redis key"},
                    "member": {"type": "string", "description": "成员名"},
                },
                "required": ["key", "member"],
            },
        ),
    ]


def build_handlers(conn: RedisConnection) -> dict[str, Callable[[dict[str, Any]], Any]]:
    h = _CollectionHandlers(conn)
    return {
        "redis_sadd": h.sadd,
        "redis_srem": h.srem,
        "redis_smembers": h.smembers,
        "redis_scard": h.scard,
        "redis_sismember": h.sismember,
        "redis_zadd": h.zadd,
        "redis_zrem": h.zrem,
        "redis_zrange": h.zrange,
        "redis_zrevrange": h.zrevrange,
        "redis_zcard": h.zcard,
        "redis_zscore": h.zscore,
        "redis_zrank": h.zrank,
        "redis_zrevrank": h.zrevrank,
    }


class _CollectionHandlers:
    def __init__(self, conn: RedisConnection):
        self._conn = conn

    # ── Set ──

    async def sadd(self, args: dict[str, Any]) -> ToolResult:
        key = args["key"]
        members: list[str] = args["members"]
        added = await self._conn.set_add(key, *members)
        return ToolResult.success(data={"key": key, "requested": len(members), "added": added})

    async def srem(self, args: dict[str, Any]) -> ToolResult:
        key = args["key"]
        members: list[str] = args["members"]
        removed = await self._conn.set_remove(key, *members)
        return ToolResult.success(data={"key": key, "requested": len(members), "removed": removed})

    async def smembers(self, args: dict[str, Any]) -> ToolResult:
        key = args["key"]
        members = await self._conn.set_members(key)
        return ToolResult.success(data={"key": key, "members": members, "count": len(members)})

    async def scard(self, args: dict[str, Any]) -> ToolResult:
        key = args["key"]
        n = await self._conn.set_card(key)
        return ToolResult.success(data={"key": key, "count": n})

    async def sismember(self, args: dict[str, Any]) -> ToolResult:
        key, member = args["key"], args["member"]
        ok = await self._conn.set_is_member(key, member)
        return ToolResult.success(data={"key": key, "member": member, "is_member": ok})

    # ── Sorted Set ──

    async def zadd(self, args: dict[str, Any]) -> ToolResult:
        key = args["key"]
        mapping: dict[str, float] = {k: float(v) for k, v in args["mapping"].items()}
        added = await self._conn.zset_add(key, mapping)
        return ToolResult.success(data={"key": key, "added": added, "count": len(mapping)})

    async def zrem(self, args: dict[str, Any]) -> ToolResult:
        key = args["key"]
        members: list[str] = args["members"]
        removed = await self._conn.zset_remove(key, *members)
        return ToolResult.success(data={"key": key, "requested": len(members), "removed": removed})

    async def _zrange(self, args: dict[str, Any], reverse: bool) -> ToolResult:
        key, start, stop = args["key"], args["start"], args["stop"]
        with_scores = args.get("with_scores", False)
        result = await self._conn.zset_range(key, start, stop, with_scores=with_scores, reverse=reverse)
        return ToolResult.success(data={"key": key, "start": start, "stop": stop, "members": result, "count": len(result)})

    async def zrange(self, args: dict[str, Any]) -> ToolResult:
        return await self._zrange(args, reverse=False)

    async def zrevrange(self, args: dict[str, Any]) -> ToolResult:
        return await self._zrange(args, reverse=True)

    async def zcard(self, args: dict[str, Any]) -> ToolResult:
        key = args["key"]
        n = await self._conn.zset_card(key)
        return ToolResult.success(data={"key": key, "count": n})

    async def zscore(self, args: dict[str, Any]) -> ToolResult:
        key, member = args["key"], args["member"]
        score = await self._conn.zset_score(key, member)
        return ToolResult.success(data={"key": key, "member": member, "score": score})

    async def zrank(self, args: dict[str, Any]) -> ToolResult:
        key, member = args["key"], args["member"]
        rank = await self._conn.zset_rank(key, member, reverse=False)
        return ToolResult.success(data={"key": key, "member": member, "rank": rank})

    async def zrevrank(self, args: dict[str, Any]) -> ToolResult:
        key, member = args["key"], args["member"]
        rank = await self._conn.zset_rank(key, member, reverse=True)
        return ToolResult.success(data={"key": key, "member": member, "rank": rank})
