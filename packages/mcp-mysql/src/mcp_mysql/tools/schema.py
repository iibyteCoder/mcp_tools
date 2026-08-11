"""Schema 查询工具 — mysql_list_databases / mysql_list_tables / mysql_describe_table."""

from collections.abc import Callable
from typing import Any

from mcp.types import Tool

from mcp_base.types import ToolResult
from mcp_mysql.connection import MySQLConnection


def get_definitions() -> list[Tool]:
    return [
        Tool(
            name="mysql_list_databases",
            description="列出 MySQL 服务器上所有数据库",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="mysql_list_tables",
            description="列出当前数据库中的所有表",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="mysql_describe_table",
            description="获取指定表的结构(字段名/类型/键/默认值等)",
            inputSchema={
                "type": "object",
                "properties": {"table_name": {"type": "string", "description": "表名"}},
                "required": ["table_name"],
            },
        ),
    ]


def build_handlers(conn: MySQLConnection) -> dict[str, Callable[[dict[str, Any]], Any]]:
    h = _SchemaHandlers(conn)
    return {
        "mysql_list_databases": h.list_databases,
        "mysql_list_tables": h.list_tables,
        "mysql_describe_table": h.describe_table,
    }


class _SchemaHandlers:
    def __init__(self, conn: MySQLConnection):
        self._conn = conn

    async def list_databases(self, _args: dict[str, Any]) -> ToolResult:
        databases = await self._conn.get_databases()
        return ToolResult.success(data={"databases": databases, "count": len(databases)})

    async def list_tables(self, _args: dict[str, Any]) -> ToolResult:
        tables = await self._conn.get_tables()
        return ToolResult.success(data={"tables": tables, "count": len(tables)})

    async def describe_table(self, args: dict[str, Any]) -> ToolResult:
        table_name = args["table_name"]
        if not table_name.strip():
            return ToolResult.error("表名不能为空")
        schema = await self._conn.get_table_schema(table_name)
        return ToolResult.success(data={"table": table_name, "schema": schema, "field_count": len(schema)})
