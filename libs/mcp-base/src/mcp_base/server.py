"""MCP 服务器基类实现."""

from abc import ABC, abstractmethod
from typing import Any

from mcp.server import Server
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from mcp_base.types import ToolResult


class BaseMCPServer(ABC):
    """MCP 服务器抽象基类.

    提供结构化的 MCP 服务器实现方式, 包含:
    - 工具注册
    - 标准化错误处理
    - 生命周期管理
    """

    def __init__(self, name: str, version: str = "0.1.0"):
        """初始化 MCP 服务器.

        参数:
            name: 服务器名称标识
            version: 服务器版本号
        """
        self._name = name
        self._version = version
        self._server = Server(name)
        self._setup_handlers()

    @property
    def server(self) -> Server:
        """获取底层 MCP 服务器实例."""
        return self._server

    @property
    def name(self) -> str:
        """获取服务器名称."""
        return self._name

    @property
    def version(self) -> str:
        """获取服务器版本."""
        return self._version

    def _setup_handlers(self) -> None:
        """设置 MCP 服务器处理器."""
        self._server.list_tools()(self._list_tools_wrapper)
        self._server.call_tool()(self._call_tool_wrapper)

    async def _list_tools_wrapper(self) -> list[Tool]:
        """工具列表处理器包装器."""
        return await self.list_tools()

    async def _call_tool_wrapper(self, name: str, arguments: dict[str, Any]) -> list[TextContent]:
        """工具调用处理器包装器, 包含错误处理."""
        try:
            result = await self.call_tool(name, arguments)
            return self._format_result(result)
        except Exception as e:
            error_result = ToolResult.error(str(e))
            return self._format_result(error_result)

    def _format_result(self, result: ToolResult) -> list[TextContent]:
        """将工具结果格式化为 TextContent."""
        import json

        return [
            TextContent(
                type="text",
                text=json.dumps(result.to_dict(), indent=2, default=str, ensure_ascii=False),
            )
        ]

    @abstractmethod
    async def list_tools(self) -> list[Tool]:
        """返回可用工具列表.

        返回:
            服务器提供的 Tool 对象列表.
        """
        pass

    @abstractmethod
    async def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """根据名称执行工具.

        参数:
            name: 要执行的工具名称
            arguments: 工具参数

        返回:
            包含执行结果的 ToolResult
        """
        pass

    async def run(self) -> None:
        """使用 stdio 传输运行 MCP 服务器."""
        async with stdio_server() as (read_stream, write_stream):
            await self._server.run(
                read_stream,
                write_stream,
                self._server.create_initialization_options(),
            )

    def create_initialization_options(self) -> InitializationOptions:
        """创建服务器初始化选项."""
        return self._server.create_initialization_options()
