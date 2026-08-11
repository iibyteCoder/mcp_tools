"""异步 Redis MCP 服务器实现."""

from typing import Any

from mcp.types import Tool

from mcp_base.server import BaseMCPServer
from mcp_base.types import ToolResult
from mcp_redis.config import RedisConfig
from mcp_redis.connection import RedisConnection
from mcp_redis.tools import build_dispatch, get_all_definitions


class RedisServer(BaseMCPServer):
    """异步 Redis 数据库操作 MCP 服务器.

    按数据类型分组提供工具:
    - 连接管理: redis_connect / disconnect / status
    - Key 管理: redis_keys / exists / type / ttl / expire / persist / rename / delete / randomkey
    - String: redis_get / set / mget / mset / incr / append / strlen
    - Hash: redis_hget / hset / hgetall / hdel / hexists / hkeys / hvals / hlen
    - List: redis_lpush / rpush / lpop / rpop / lrange / llen / lindex / ltrim
    - Set + ZSet: redis_sadd / srem / smembers / scard / sismember / zadd / zrem / zrange / zrevrange / zcard / zscore / zrank / zrevrank
    - 服务器: redis_info / dbsize / ping / flushdb / pipeline
    """

    def __init__(self, config: RedisConfig | None = None):
        super().__init__(name="mcp-redis", version="0.1.0")
        self._config = config or RedisConfig()
        self._connection = RedisConnection(self._config)
        self._dispatch = build_dispatch(self._connection)

    async def list_tools(self) -> list[Tool]:
        return get_all_definitions()

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        handler = self._dispatch.get(name)
        if handler is None:
            return ToolResult.error(f"未知工具: {name}")
        return await handler(arguments)
