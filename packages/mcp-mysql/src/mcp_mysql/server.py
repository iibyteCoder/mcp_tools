"""异步 MySQL MCP 服务器实现。"""

from typing import Any

from mcp.types import Tool

from mcp_base.server import BaseMCPServer
from mcp_base.types import ToolResult
from mcp_mysql.config import MySQLConfig
from mcp_mysql.connection import MySQLConnection
from mcp_mysql.tools import MySQLTools


class MySQLServer(BaseMCPServer):
    """异步 MySQL 数据库操作 MCP 服务器.

    提供以下工具:
    - 连接/断开 MySQL 数据库
    - 查询连接状态
    - 执行查询 (自动分页)
    - 查看数据库结构

    所有操作均为异步以获得更好的性能.
    """

    def __init__(self, config: MySQLConfig | None = None):
        """初始化 MySQL MCP 服务器.

        参数:
            config: MySQL 配置. 未提供时使用默认值/环境变量.
        """
        super().__init__(name="mcp-mysql", version="0.1.0")
        self._config = config or MySQLConfig()
        self._connection = MySQLConnection(self._config)
        self._tools = MySQLTools(self._connection)

    async def list_tools(self) -> list[Tool]:
        """返回可用的 MySQL 工具。"""
        return MySQLTools.get_tool_definitions()

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """根据名称异步执行工具。

        参数:
            name: 要执行的工具名称。
            arguments: 工具参数。

        返回:
            包含执行结果的 ToolResult。
        """
        tool_handlers = {
            "mysql_connect": self._tools.connect,
            "mysql_disconnect": self._tools.disconnect,
            "mysql_status": self._tools.status,
            "mysql_query": self._tools.query,
            "mysql_execute": self._tools.execute,
            "mysql_list_databases": self._tools.list_databases,
            "mysql_list_tables": self._tools.list_tables,
            "mysql_describe_table": self._tools.describe_table,
        }

        handler = tool_handlers.get(name)
        if handler is None:
            return ToolResult.error(f"未知工具: {name}")

        return await handler(arguments)
