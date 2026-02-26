"""Async MySQL MCP Server implementation."""

from typing import Any

from mcp.types import Tool

from mcp_base.server import BaseMCPServer
from mcp_base.types import ToolResult
from mcp_mysql.config import MySQLConfig
from mcp_mysql.connection import MySQLConnection
from mcp_mysql.tools import MySQLTools


class MySQLServer(BaseMCPServer):
    """Async MCP Server for MySQL database operations.

    Provides tools for:
    - Connecting/disconnecting from MySQL
    - Executing queries
    - Inspecting database schema

    All operations are async for better performance.
    """

    def __init__(self, config: MySQLConfig | None = None):
        """Initialize MySQL MCP server.

        Args:
            config: MySQL configuration. Uses defaults/env if not provided.
        """
        super().__init__(name="mcp-mysql", version="0.1.0")
        self._config = config or MySQLConfig()
        self._connection = MySQLConnection(self._config)
        self._tools = MySQLTools(self._connection)

    async def list_tools(self) -> list[Tool]:
        """Return available MySQL tools."""
        return MySQLTools.get_tool_definitions()

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """Execute a tool by name asynchronously.

        Args:
            name: Tool name to execute.
            arguments: Tool arguments.

        Returns:
            ToolResult with execution outcome.
        """
        tool_handlers = {
            "mysql_connect": self._tools.connect,
            "mysql_disconnect": self._tools.disconnect,
            "mysql_query": self._tools.query,
            "mysql_execute": self._tools.execute,
            "mysql_list_databases": self._tools.list_databases,
            "mysql_list_tables": self._tools.list_tables,
            "mysql_describe_table": self._tools.describe_table,
        }

        handler = tool_handlers.get(name)
        if handler is None:
            return ToolResult.error(f"Unknown tool: {name}")

        return await handler(arguments)
