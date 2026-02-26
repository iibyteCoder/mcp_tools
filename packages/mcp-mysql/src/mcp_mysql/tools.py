"""Async tool definitions for MySQL MCP server."""

from typing import Any

from mcp.types import Tool

from mcp_base.types import ToolResult
from mcp_mysql.connection import MySQLConnection


class MySQLTools:
    """Async MySQL MCP tools implementation.

    Each method corresponds to a tool that can be called by MCP clients.
    All methods are async for non-blocking I/O operations.
    """

    def __init__(self, connection: MySQLConnection):
        """Initialize tools with database connection.

        Args:
            connection: Async MySQL connection manager instance.
        """
        self._conn = connection

    @staticmethod
    def get_tool_definitions() -> list[Tool]:
        """Return all tool definitions for registration.

        Returns:
            List of Tool objects.
        """
        return [
            Tool(
                name="mysql_connect",
                description="Connect to MySQL database with specified connection parameters",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "host": {
                            "type": "string",
                            "description": "MySQL server host (default: localhost)",
                        },
                        "port": {
                            "type": "integer",
                            "description": "MySQL server port (default: 3306)",
                        },
                        "user": {
                            "type": "string",
                            "description": "MySQL username (default: root)",
                        },
                        "password": {
                            "type": "string",
                            "description": "MySQL password",
                        },
                        "database": {
                            "type": "string",
                            "description": "Database name to connect to",
                        },
                    },
                    "required": [],
                },
            ),
            Tool(
                name="mysql_disconnect",
                description="Disconnect from the current MySQL database",
                inputSchema={"type": "object", "properties": {}},
            ),
            Tool(
                name="mysql_query",
                description="Execute a SELECT query on the MySQL database",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The SELECT SQL query to execute",
                        },
                    },
                    "required": ["query"],
                },
            ),
            Tool(
                name="mysql_execute",
                description="Execute an INSERT, UPDATE, or DELETE query on the MySQL database",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The SQL query to execute (INSERT/UPDATE/DELETE)",
                        },
                    },
                    "required": ["query"],
                },
            ),
            Tool(
                name="mysql_list_databases",
                description="List all available databases on the MySQL server",
                inputSchema={"type": "object", "properties": {}},
            ),
            Tool(
                name="mysql_list_tables",
                description="List all tables in the current database",
                inputSchema={"type": "object", "properties": {}},
            ),
            Tool(
                name="mysql_describe_table",
                description="Get the schema/structure of a specific table",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "table_name": {
                            "type": "string",
                            "description": "The name of the table to describe",
                        },
                    },
                    "required": ["table_name"],
                },
            ),
        ]

    async def connect(self, arguments: dict[str, Any]) -> ToolResult:
        """Connect to MySQL database asynchronously.

        Args:
            arguments: Connection parameters (host, port, user, password, database).

        Returns:
            ToolResult with connection status.
        """
        await self._conn.connect(**arguments)

        return ToolResult.success(
            message=f"Connected to MySQL at {self._conn.config.host}:{self._conn.config.port}",
            data={"database": self._conn.config.database or "none selected"},
        )

    async def disconnect(self, _arguments: dict[str, Any]) -> ToolResult:
        """Disconnect from MySQL database asynchronously.

        Args:
            _arguments: Unused (required for consistent interface).

        Returns:
            ToolResult with disconnect status.
        """
        await self._conn.disconnect()
        return ToolResult.success(message="Disconnected from MySQL")

    async def query(self, arguments: dict[str, Any]) -> ToolResult:
        """Execute SELECT query asynchronously.

        Args:
            arguments: Contains 'query' key with SQL string.

        Returns:
            ToolResult with query results.
        """
        query = arguments.get("query", "")
        if not query:
            return ToolResult.error("Query is required")

        results = await self._conn.execute_query(query)
        return ToolResult.success(
            message=f"Query returned {len(results)} rows",
            data=results,
        )

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        """Execute INSERT/UPDATE/DELETE query asynchronously.

        Args:
            arguments: Contains 'query' key with SQL string.

        Returns:
            ToolResult with execution stats.
        """
        query = arguments.get("query", "")
        if not query:
            return ToolResult.error("Query is required")

        result = await self._conn.execute_update(query)
        return ToolResult.success(
            message=f"Affected {result['affected_rows']} rows",
            data=result,
        )

    async def list_databases(self, _arguments: dict[str, Any]) -> ToolResult:
        """List all databases asynchronously.

        Args:
            _arguments: Unused.

        Returns:
            ToolResult with database list.
        """
        databases = await self._conn.get_databases()
        return ToolResult.success(
            message=f"Found {len(databases)} databases",
            data={"databases": databases, "count": len(databases)},
        )

    async def list_tables(self, _arguments: dict[str, Any]) -> ToolResult:
        """List all tables in current database asynchronously.

        Args:
            _arguments: Unused.

        Returns:
            ToolResult with table list.
        """
        tables = await self._conn.get_tables()
        return ToolResult.success(
            message=f"Found {len(tables)} tables",
            data={"tables": tables, "count": len(tables)},
        )

    async def describe_table(self, arguments: dict[str, Any]) -> ToolResult:
        """Describe table structure asynchronously.

        Args:
            arguments: Contains 'table_name' key.

        Returns:
            ToolResult with table schema.
        """
        table_name = arguments.get("table_name", "")
        if not table_name:
            return ToolResult.error("table_name is required")

        schema = await self._conn.get_table_schema(table_name)
        return ToolResult.success(
            message=f"Table '{table_name}' has {len(schema)} columns",
            data={"table": table_name, "schema": schema},
        )
