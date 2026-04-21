"""异步 Neo4j MCP 服务器实现。"""

from typing import Any

from mcp.types import Tool

from mcp_base.server import BaseMCPServer
from mcp_base.types import ToolResult
from mcp_neo4j.config import Neo4jConfig
from mcp_neo4j.connection import Neo4jConnection
from mcp_neo4j.tools import Neo4jTools


class Neo4jServer(BaseMCPServer):
    """异步 Neo4j 数据库操作 MCP 服务器.

    提供以下工具:
    - 连接/断开 Neo4j 数据库
    - 查询连接状态
    - 执行 Cypher 查询 (自动分页)
    - 查看图结构 (标签, 关系, 属性)

    所有操作均为异步以获得更好的性能.
    """

    def __init__(self, config: Neo4jConfig | None = None):
        """初始化 Neo4j MCP 服务器.

        参数:
            config: Neo4j 配置. 未提供时使用默认值/环境变量.
        """
        super().__init__(name="mcp-neo4j", version="0.1.0")
        self._config = config or Neo4jConfig()
        self._connection = Neo4jConnection(self._config)
        self._tools = Neo4jTools(self._connection)

    async def list_tools(self) -> list[Tool]:
        """返回可用的 Neo4j 工具。"""
        return Neo4jTools.get_tool_definitions()

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """根据名称异步执行工具。

        参数:
            name: 要执行的工具名称。
            arguments: 工具参数。

        返回:
            包含执行结果的 ToolResult。
        """
        tool_handlers = {
            "neo4j_connect": self._tools.connect,
            "neo4j_disconnect": self._tools.disconnect,
            "neo4j_status": self._tools.status,
            "neo4j_query": self._tools.query,
            "neo4j_execute": self._tools.execute,
            "neo4j_list_labels": self._tools.list_labels,
            "neo4j_list_relationship_types": self._tools.list_relationship_types,
            "neo4j_list_properties": self._tools.list_properties,
            "neo4j_describe_label": self._tools.describe_label,
        }

        handler = tool_handlers.get(name)
        if handler is None:
            return ToolResult.error(f"未知工具: {name}")

        return await handler(arguments)
