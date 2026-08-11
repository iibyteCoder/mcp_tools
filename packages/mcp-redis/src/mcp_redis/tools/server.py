"""服务器/诊断工具 — INFO/DBSIZE/PING/FLUSHDB/PIPELINE."""

from collections.abc import Callable
from typing import Any

from mcp.types import Tool

from mcp_base.types import ToolResult
from mcp_redis.connection import RedisConnection


def get_definitions() -> list[Tool]:
    return [
        Tool(
            name="redis_info",
            description="获取 Redis 服务器信息.section 可选: server/clients/memory/stats/replication/cpu/keyspace, 默认 default",
            inputSchema={
                "type": "object",
                "properties": {"section": {"type": "string", "description": "信息分类, 默认 default"}},
            },
        ),
        Tool(
            name="redis_dbsize",
            description="获取当前数据库的 key 总数",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="redis_ping",
            description="测试 Redis 连接是否正常, 正常返回 true",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="redis_flushdb",
            description="⚠️ 删除当前数据库的所有 key.必须设置 confirm=true 才会执行",
            inputSchema={
                "type": "object",
                "properties": {"confirm": {"type": "boolean", "description": "确认删除, 必须为 true"}},
                "required": ["confirm"],
            },
        ),
        Tool(
            name="redis_pipeline",
            description="管道批量执行多条 Redis 命令.commands 格式: [[\"SET\",\"k\",\"v\"], [\"GET\",\"k\"]]",
            inputSchema={
                "type": "object",
                "properties": {
                    "commands": {
                        "type": "array",
                        "items": {"type": "array", "items": {"type": "string"}},
                        "description": "命令列表, 每条为 [命令名, 参数...]",
                    },
                },
                "required": ["commands"],
            },
        ),
    ]


def build_handlers(conn: RedisConnection) -> dict[str, Callable[[dict[str, Any]], Any]]:
    h = _ServerHandlers(conn)
    return {
        "redis_info": h.info,
        "redis_dbsize": h.dbsize,
        "redis_ping": h.ping,
        "redis_flushdb": h.flushdb,
        "redis_pipeline": h.pipeline,
    }


class _ServerHandlers:
    def __init__(self, conn: RedisConnection):
        self._conn = conn

    async def info(self, args: dict[str, Any]) -> ToolResult:
        section = args.get("section", "default")
        info_data = await self._conn.server_info(section)
        return ToolResult.success(data={"section": section, "info": info_data})

    async def dbsize(self, _args: dict[str, Any]) -> ToolResult:
        n = await self._conn.server_dbsize()
        return ToolResult.success(data={"dbsize": n})

    async def ping(self, _args: dict[str, Any]) -> ToolResult:
        ok = await self._conn.server_ping()
        return ToolResult.success(data={"pong": ok})

    async def flushdb(self, args: dict[str, Any]) -> ToolResult:
        if not args.get("confirm"):
            return ToolResult.error("⚠️ flushdb 需要 confirm=true 才会执行")
        await self._conn.server_flushdb()
        return ToolResult.success(data={"flushed": True})

    async def pipeline(self, args: dict[str, Any]) -> ToolResult:
        commands: list[list[str]] = args["commands"]
        results = await self._conn.pipeline_execute(commands)
        return ToolResult.success(
            data={
                "count": len(commands),
                "results": [
                    {"index": i, "command": " ".join(cmd), "result": str(res)}
                    for i, (cmd, res) in enumerate(zip(commands, results, strict=True))
                ],
            },
        )
