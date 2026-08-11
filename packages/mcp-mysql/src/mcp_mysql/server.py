"""异步 MySQL MCP 服务器实现."""

from typing import Any

from mcp.types import Tool

from mcp_base.server import BaseMCPServer
from mcp_base.types import ToolResult
from mcp_mysql.config import MySQLConfig
from mcp_mysql.connection import MySQLConnection
from mcp_mysql.tools import build_dispatch, get_all_definitions


class MySQLServer(BaseMCPServer):
    """异步 MySQL 数据库操作 MCP 服务器.

    提供工具:
    - 连接管理: mysql_connect / disconnect / status
    - 查询: mysql_query (SELECT 分页) / mysql_execute (INSERT/UPDATE/DELETE)
    - Schema: mysql_list_databases / list_tables / describe_table
    """

    def __init__(self, config: MySQLConfig | None = None):
        super().__init__(name="mcp-mysql", version="0.1.0")
        self._config = config or MySQLConfig()
        self._connection = MySQLConnection(self._config)
        self._dispatch = build_dispatch(self._connection)

    async def list_tools(self) -> list[Tool]:
        return get_all_definitions()

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        handler = self._dispatch.get(name)
        if handler is None:
            return ToolResult.error(f"未知工具: {name}")
        return await handler(arguments)
