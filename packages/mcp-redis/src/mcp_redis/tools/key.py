"""Key 管理工具 — 遍历/存在/类型/过期/重命名/删除."""

from collections.abc import Callable
from typing import Any

from mcp.types import Tool

from mcp_base.types import PaginationParams, ToolResult
from mcp_redis.connection import RedisConnection

_KEY_SCHEMA = {"key": {"type": "string", "description": "Redis key"}}


def get_definitions() -> list[Tool]:
    return [
        Tool(
            name="redis_keys",
            description="遍历匹配 pattern 的 key(SCAN 方式,不分页时返回所有匹配).设置 page/page_size 启用分页",
            inputSchema={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Glob 匹配模式 (如 user:*), 默认 *"},
                    "page": {"type": "integer", "description": "页码, 1 开始, 不分页时不传"},
                    "page_size": {"type": "integer", "description": "每页数量 1~500, 默认 50"},
                },
            },
        ),
        Tool(
            name="redis_exists",
            description="检查 key 是否存在",
            inputSchema={"type": "object", "properties": _KEY_SCHEMA, "required": ["key"]},
        ),
        Tool(
            name="redis_type",
            description="获取 key 的数据类型(string/hash/list/set/zset/none)",
            inputSchema={"type": "object", "properties": _KEY_SCHEMA, "required": ["key"]},
        ),
        Tool(
            name="redis_ttl",
            description="获取 key 剩余生存时间(秒).-1 表示永久,-2 表示不存在",
            inputSchema={"type": "object", "properties": _KEY_SCHEMA, "required": ["key"]},
        ),
        Tool(
            name="redis_expire",
            description="设置 key 过期时间(秒)",
            inputSchema={
                "type": "object",
                "properties": {
                    "key": _KEY_SCHEMA["key"],
                    "seconds": {"type": "integer", "description": "过期秒数"},
                },
                "required": ["key", "seconds"],
            },
        ),
        Tool(
            name="redis_persist",
            description="移除 key 的过期时间,使其永久有效",
            inputSchema={"type": "object", "properties": _KEY_SCHEMA, "required": ["key"]},
        ),
        Tool(
            name="redis_rename",
            description="重命名 key, newkey 已存在时将被覆盖",
            inputSchema={
                "type": "object",
                "properties": {
                    "key": _KEY_SCHEMA["key"],
                    "newkey": {"type": "string", "description": "新 key 名"},
                },
                "required": ["key", "newkey"],
            },
        ),
        Tool(
            name="redis_delete",
            description="删除一个或多个 key,返回实际删除数",
            inputSchema={
                "type": "object",
                "properties": {"keys": {"type": "array", "items": {"type": "string"}, "description": "要删除的 key 列表"}},
                "required": ["keys"],
            },
        ),
        Tool(
            name="redis_randomkey",
            description="从当前数据库随机返回一个 key",
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


def build_handlers(conn: RedisConnection) -> dict[str, Callable[[dict[str, Any]], Any]]:
    h = _KeyHandlers(conn)
    return {
        "redis_keys": h.keys,
        "redis_exists": h.exists,
        "redis_type": h.type,
        "redis_ttl": h.ttl,
        "redis_expire": h.expire,
        "redis_persist": h.persist,
        "redis_rename": h.rename,
        "redis_delete": h.delete,
        "redis_randomkey": h.randomkey,
    }


class _KeyHandlers:
    def __init__(self, conn: RedisConnection):
        self._conn = conn

    async def keys(self, args: dict[str, Any]) -> ToolResult:
        pattern = args.get("pattern", "*")
        pag = PaginationParams.from_args(args)

        matched, _ = await self._conn.scan_keys(pattern, skip=pag.offset, limit=pag.fetch_limit)

        has_more = len(matched) > pag.page_size
        rows = matched[: pag.page_size]

        data: dict[str, Any] = {
            "keys": rows, "page": pag.page, "page_size": pag.page_size,
            "pattern": pattern, "has_more": has_more, "count": len(rows),
        }
        if has_more:
            data["next_page"] = pag.page + 1

        return ToolResult.success(
            message=f"匹配 '{pattern}': 第{pag.page}页 {len(rows)} 个"
                    + (" (还有更多)" if has_more else " (已全部)"),
            data=data,
        )

    async def exists(self, args: dict[str, Any]) -> ToolResult:
        key = args["key"]
        ok = await self._conn.key_exists(key)
        return ToolResult.success(data={"key": key, "exists": ok})

    async def type(self, args: dict[str, Any]) -> ToolResult:
        key = args["key"]
        t = await self._conn.key_type(key)
        return ToolResult.success(data={"key": key, "type": t})

    async def ttl(self, args: dict[str, Any]) -> ToolResult:
        key = args["key"]
        t = await self._conn.key_ttl(key)
        return ToolResult.success(data={"key": key, "ttl": t})

    async def expire(self, args: dict[str, Any]) -> ToolResult:
        key, sec = args["key"], args["seconds"]
        ok = await self._conn.key_expire(key, sec)
        return ToolResult.success(data={"key": key, "seconds": sec, "ok": ok})

    async def persist(self, args: dict[str, Any]) -> ToolResult:
        key = args["key"]
        ok = await self._conn.key_persist(key)
        return ToolResult.success(data={"key": key, "ok": ok})

    async def rename(self, args: dict[str, Any]) -> ToolResult:
        key, nk = args["key"], args["newkey"]
        await self._conn.key_rename(key, nk)
        return ToolResult.success(data={"old": key, "new": nk})

    async def delete(self, args: dict[str, Any]) -> ToolResult:
        keys: list[str] = args["keys"]
        n = await self._conn.key_delete(*keys)
        return ToolResult.success(data={"requested": len(keys), "deleted": n})

    async def randomkey(self, _args: dict[str, Any]) -> ToolResult:
        k = await self._conn.key_random()
        return ToolResult.success(data={"key": k})
