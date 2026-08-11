"""工具聚合 — 按 Redis 数据类型拆分, 各模块自含定义与处理器."""

from collections.abc import Callable
from typing import Any

from mcp.types import Tool

from mcp_redis.connection import RedisConnection

from . import collection, connection, hash_ops, key, list_ops, server, string

_Handler = Callable[[dict[str, Any]], Any]

_MODULES = (connection, key, string, hash_ops, list_ops, collection, server)


def get_all_definitions() -> list[Tool]:
    """聚合所有子模块的工具定义."""
    tools: list[Tool] = []
    for mod in _MODULES:
        tools.extend(mod.get_definitions())
    return tools


def build_dispatch(conn: RedisConnection) -> dict[str, _Handler]:
    """构建 tool_name → handler 的完整分发映射."""
    dispatch: dict[str, _Handler] = {}
    for mod in _MODULES:
        dispatch.update(mod.build_handlers(conn))
    return dispatch
