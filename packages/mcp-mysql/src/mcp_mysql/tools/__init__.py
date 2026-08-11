"""MySQL 工具聚合 — 按职责拆分, 各模块自含定义与处理器."""

from collections.abc import Callable
from typing import Any

from mcp.types import Tool

from mcp_mysql.connection import MySQLConnection

from . import connection, query, schema

_Handler = Callable[[dict[str, Any]], Any]

_MODULES = (connection, query, schema)


def get_all_definitions() -> list[Tool]:
    """聚合所有子模块的工具定义."""
    tools: list[Tool] = []
    for mod in _MODULES:
        tools.extend(mod.get_definitions())
    return tools


def build_dispatch(conn: MySQLConnection) -> dict[str, _Handler]:
    """构建 tool_name -> handler 的完整分发映射."""
    dispatch: dict[str, _Handler] = {}
    for mod in _MODULES:
        dispatch.update(mod.build_handlers(conn))
    return dispatch
