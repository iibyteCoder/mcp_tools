"""Async tool definitions for Neo4j MCP server."""

from typing import Any

from mcp.types import Tool

from mcp_base.types import ToolResult
from mcp_neo4j.connection import Neo4jConnection


class Neo4jTools:
    """Async Neo4j MCP tools implementation.

    Each method corresponds to a tool that can be called by MCP clients.
    All methods are async for non-blocking I/O operations.
    """

    def __init__(self, connection: Neo4jConnection):
        """Initialize tools with database connection.

        Args:
            connection: Async Neo4j connection manager instance.
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
                name="neo4j_connect",
                description="Connect to Neo4j database with specified connection parameters",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "uri": {
                            "type": "string",
                            "description": "Neo4j server URI (default: bolt://localhost:7687)",
                        },
                        "user": {
                            "type": "string",
                            "description": "Neo4j username (default: neo4j)",
                        },
                        "password": {
                            "type": "string",
                            "description": "Neo4j password",
                        },
                        "database": {
                            "type": "string",
                            "description": "Database name (default: neo4j)",
                        },
                    },
                    "required": [],
                },
            ),
            Tool(
                name="neo4j_disconnect",
                description="Disconnect from the current Neo4j database",
                inputSchema={"type": "object", "properties": {}},
            ),
            Tool(
                name="neo4j_query",
                description="Execute a Cypher query (MATCH) on the Neo4j database",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The Cypher query to execute",
                        },
                        "parameters": {
                            "type": "object",
                            "description": "Query parameters (optional)",
                        },
                    },
                    "required": ["query"],
                },
            ),
            Tool(
                name="neo4j_execute",
                description="Execute a write query (CREATE, MERGE, DELETE, SET) on the Neo4j database",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The Cypher write query to execute",
                        },
                        "parameters": {
                            "type": "object",
                            "description": "Query parameters (optional)",
                        },
                    },
                    "required": ["query"],
                },
            ),
            Tool(
                name="neo4j_list_labels",
                description="List all node labels in the database",
                inputSchema={"type": "object", "properties": {}},
            ),
            Tool(
                name="neo4j_list_relationship_types",
                description="List all relationship types in the database",
                inputSchema={"type": "object", "properties": {}},
            ),
            Tool(
                name="neo4j_list_properties",
                description="List all property keys in the database",
                inputSchema={"type": "object", "properties": {}},
            ),
            Tool(
                name="neo4j_describe_label",
                description="Get the schema/properties of nodes with a specific label",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "label": {
                            "type": "string",
                            "description": "The node label to describe",
                        },
                    },
                    "required": ["label"],
                },
            ),
        ]

    async def connect(self, arguments: dict[str, Any]) -> ToolResult:
        """Connect to Neo4j database asynchronously.

        Args:
            arguments: Connection parameters (uri, user, password, database).

        Returns:
            ToolResult with connection status.
        """
        await self._conn.connect(**arguments)

        return ToolResult.success(
            message=f"Connected to Neo4j at {self._conn.config.uri}",
            data={"database": self._conn.config.database},
        )

    async def disconnect(self, _arguments: dict[str, Any]) -> ToolResult:
        """Disconnect from Neo4j database asynchronously.

        Args:
            _arguments: Unused (required for consistent interface).

        Returns:
            ToolResult with disconnect status.
        """
        await self._conn.disconnect()
        return ToolResult.success(message="Disconnected from Neo4j")

    async def query(self, arguments: dict[str, Any]) -> ToolResult:
        """Execute Cypher query asynchronously.

        Args:
            arguments: Contains 'query' key with Cypher string and optional 'parameters'.

        Returns:
            ToolResult with query results.
        """
        query = arguments.get("query", "")
        if not query:
            return ToolResult.error("Query is required")

        parameters = arguments.get("parameters")
        results = await self._conn.execute_query(query, parameters)
        return ToolResult.success(
            message=f"Query returned {len(results)} records",
            data=results,
        )

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        """Execute write query asynchronously.

        Args:
            arguments: Contains 'query' key with Cypher string and optional 'parameters'.

        Returns:
            ToolResult with execution stats.
        """
        query = arguments.get("query", "")
        if not query:
            return ToolResult.error("Query is required")

        parameters = arguments.get("parameters")
        result = await self._conn.execute_write(query, parameters)
        return ToolResult.success(
            message="Query executed successfully",
            data=result,
        )

    async def list_labels(self, _arguments: dict[str, Any]) -> ToolResult:
        """List all node labels asynchronously.

        Args:
            _arguments: Unused.

        Returns:
            ToolResult with label list.
        """
        labels = await self._conn.get_labels()
        return ToolResult.success(
            message=f"Found {len(labels)} labels",
            data={"labels": labels, "count": len(labels)},
        )

    async def list_relationship_types(self, _arguments: dict[str, Any]) -> ToolResult:
        """List all relationship types asynchronously.

        Args:
            _arguments: Unused.

        Returns:
            ToolResult with relationship type list.
        """
        rel_types = await self._conn.get_relationship_types()
        return ToolResult.success(
            message=f"Found {len(rel_types)} relationship types",
            data={"relationship_types": rel_types, "count": len(rel_types)},
        )

    async def list_properties(self, _arguments: dict[str, Any]) -> ToolResult:
        """List all property keys asynchronously.

        Args:
            _arguments: Unused.

        Returns:
            ToolResult with property key list.
        """
        properties = await self._conn.get_property_keys()
        return ToolResult.success(
            message=f"Found {len(properties)} property keys",
            data={"properties": properties, "count": len(properties)},
        )

    async def describe_label(self, arguments: dict[str, Any]) -> ToolResult:
        """Describe node label structure asynchronously.

        Args:
            arguments: Contains 'label' key.

        Returns:
            ToolResult with label schema.
        """
        label = arguments.get("label", "")
        if not label:
            return ToolResult.error("label is required")

        schema = await self._conn.get_node_schema(label)
        return ToolResult.success(
            message=f"Label '{label}' has {len(schema)} properties",
            data={"label": label, "schema": schema},
        )
