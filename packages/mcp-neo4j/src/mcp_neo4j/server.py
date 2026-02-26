"""Async Neo4j MCP Server implementation."""

from typing import Any

from mcp.types import Tool

from mcp_base.server import BaseMCPServer
from mcp_base.types import ToolResult
from mcp_neo4j.config import Neo4jConfig
from mcp_neo4j.connection import Neo4jConnection
from mcp_neo4j.tools import Neo4jTools


class Neo4jServer(BaseMCPServer):
    """Async MCP Server for Neo4j database operations.

    Provides tools for:
    - Connecting/disconnecting from Neo4j
    - Executing Cypher queries
    - Inspecting graph schema (labels, relationships, properties)

    All operations are async for better performance.
    """

    def __init__(self, config: Neo4jConfig | None = None):
        """Initialize Neo4j MCP server.

        Args:
            config: Neo4j configuration. Uses defaults/env if not provided.
        """
        super().__init__(name="mcp-neo4j", version="0.1.0")
        self._config = config or Neo4jConfig()
        self._connection = Neo4jConnection(self._config)
        self._tools = Neo4jTools(self._connection)

    async def list_tools(self) -> list[Tool]:
        """Return available Neo4j tools."""
        return Neo4jTools.get_tool_definitions()

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """Execute a tool by name asynchronously.

        Args:
            name: Tool name to execute.
            arguments: Tool arguments.

        Returns:
            ToolResult with execution outcome.
        """
        tool_handlers = {
            "neo4j_connect": self._tools.connect,
            "neo4j_disconnect": self._tools.disconnect,
            "neo4j_query": self._tools.query,
            "neo4j_execute": self._tools.execute,
            "neo4j_list_labels": self._tools.list_labels,
            "neo4j_list_relationship_types": self._tools.list_relationship_types,
            "neo4j_list_properties": self._tools.list_properties,
            "neo4j_describe_label": self._tools.describe_label,
        }

        handler = tool_handlers.get(name)
        if handler is None:
            return ToolResult.error(f"Unknown tool: {name}")

        return await handler(arguments)
