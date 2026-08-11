"""异步 Neo4j MCP 服务器实现."""

from typing import Any

from mcp.types import Tool

from mcp_base.server import BaseMCPServer
from mcp_base.types import ToolResult
from mcp_neo4j.config import Neo4jConfig
from mcp_neo4j.connection import Neo4jConnection
from mcp_neo4j.tools import build_dispatch, get_all_definitions


class Neo4jServer(BaseMCPServer):
    """异步 Neo4j 图数据库操作 MCP 服务器.

    提供工具:
    - 连接管理: neo4j_connect / disconnect / status
    - 查询: neo4j_query (MATCH 分页) / neo4j_execute (CREATE/MERGE/DELETE/SET)
    - Schema: neo4j_list_labels / list_relationship_types / list_properties / describe_label
    """

    def __init__(self, config: Neo4jConfig | None = None):
        super().__init__(name="mcp-neo4j", version="0.1.0")
        self._config = config or Neo4jConfig()
        self._connection = Neo4jConnection(self._config)
        self._dispatch = build_dispatch(self._connection)

    async def list_tools(self) -> list[Tool]:
        return get_all_definitions()

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        handler = self._dispatch.get(name)
        if handler is None:
            return ToolResult.error(f"未知工具: {name}")
        return await handler(arguments)
