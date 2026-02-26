"""Base MCP Server implementation."""

from abc import ABC, abstractmethod
from typing import Any

from mcp.server import Server
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from mcp_base.types import ToolResult


class BaseMCPServer(ABC):
    """Abstract base class for MCP servers.

    Provides a structured way to implement MCP servers with:
    - Tool registration
    - Standardized error handling
    - Lifecycle management
    """

    def __init__(self, name: str, version: str = "0.1.0"):
        """Initialize the MCP server.

        Args:
            name: Server name identifier
            version: Server version
        """
        self._name = name
        self._version = version
        self._server = Server(name)
        self._setup_handlers()

    @property
    def server(self) -> Server:
        """Get the underlying MCP server instance."""
        return self._server

    @property
    def name(self) -> str:
        """Get the server name."""
        return self._name

    @property
    def version(self) -> str:
        """Get the server version."""
        return self._version

    def _setup_handlers(self) -> None:
        """Set up MCP server handlers."""
        self._server.list_tools()(self._list_tools_wrapper)  # type: ignore[misc]
        self._server.call_tool()(self._call_tool_wrapper)  # type: ignore[misc]

    async def _list_tools_wrapper(self) -> list[Tool]:
        """Wrapper for list_tools handler."""
        return await self.list_tools()

    async def _call_tool_wrapper(self, name: str, arguments: dict[str, Any]) -> list[TextContent]:
        """Wrapper for call_tool handler with error handling."""
        try:
            result = await self.call_tool(name, arguments)
            return self._format_result(result)
        except Exception as e:
            error_result = ToolResult.error(str(e))
            return self._format_result(error_result)

    def _format_result(self, result: ToolResult) -> list[TextContent]:
        """Format tool result as TextContent."""
        import json

        return [
            TextContent(
                type="text",
                text=json.dumps(result.to_dict(), indent=2, default=str, ensure_ascii=False),
            )
        ]

    @abstractmethod
    async def list_tools(self) -> list[Tool]:
        """Return list of available tools.

        Returns:
            List of Tool objects that this server provides.
        """
        pass

    @abstractmethod
    async def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """Execute a tool by name.

        Args:
            name: Tool name to execute
            arguments: Tool arguments

        Returns:
            ToolResult with execution outcome
        """
        pass

    async def run(self) -> None:
        """Run the MCP server using stdio transport."""
        async with stdio_server() as (read_stream, write_stream):
            await self._server.run(
                read_stream,
                write_stream,
                self._server.create_initialization_options(),
            )

    def create_initialization_options(self) -> InitializationOptions:
        """Create initialization options for the server."""
        return self._server.create_initialization_options()
