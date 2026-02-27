"""MySQL MCP 服务器的异步工具定义。"""

from typing import Any

from mcp.types import Tool

from mcp_base.types import ToolResult
from mcp_mysql.connection import MySQLConnection


class MySQLTools:
    """异步 MySQL MCP 工具实现。

    每个方法对应一个可被 MCP 客户端调用的工具。
    所有方法均为异步以支持非阻塞 I/O 操作。
    """

    def __init__(self, connection: MySQLConnection):
        """使用数据库连接初始化工具。

        参数:
            connection: 异步 MySQL 连接管理器实例。
        """
        self._conn = connection

    @staticmethod
    def get_tool_definitions() -> list[Tool]:
        """返回所有工具定义用于注册。

        返回:
            Tool 对象列表。
        """
        return [
            Tool(
                name="mysql_connect",
                description="使用指定的连接参数连接到 MySQL 数据库",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "host": {
                            "type": "string",
                            "description": "MySQL 服务器地址（默认: localhost）",
                        },
                        "port": {
                            "type": "integer",
                            "description": "MySQL 服务器端口（默认: 3306）",
                        },
                        "user": {
                            "type": "string",
                            "description": "MySQL 用户名（默认: root）",
                        },
                        "password": {
                            "type": "string",
                            "description": "MySQL 密码",
                        },
                        "database": {
                            "type": "string",
                            "description": "要连接的数据库名称",
                        },
                    },
                    "required": [],
                },
            ),
            Tool(
                name="mysql_disconnect",
                description="断开当前 MySQL 数据库连接",
                inputSchema={"type": "object", "properties": {}},
            ),
            Tool(
                name="mysql_query",
                description="在 MySQL 数据库上执行 SELECT 查询",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "要执行的 SELECT SQL 查询语句",
                        },
                    },
                    "required": ["query"],
                },
            ),
            Tool(
                name="mysql_execute",
                description="在 MySQL 数据库上执行 INSERT、UPDATE 或 DELETE 语句",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "要执行的 SQL 语句（INSERT/UPDATE/DELETE）",
                        },
                    },
                    "required": ["query"],
                },
            ),
            Tool(
                name="mysql_list_databases",
                description="列出 MySQL 服务器上所有可用的数据库",
                inputSchema={"type": "object", "properties": {}},
            ),
            Tool(
                name="mysql_list_tables",
                description="列出当前数据库中的所有表",
                inputSchema={"type": "object", "properties": {}},
            ),
            Tool(
                name="mysql_describe_table",
                description="获取指定表的结构信息",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "table_name": {
                            "type": "string",
                            "description": "要查看结构的表名",
                        },
                    },
                    "required": ["table_name"],
                },
            ),
        ]

    async def connect(self, arguments: dict[str, Any]) -> ToolResult:
        """异步连接到 MySQL 数据库。

        参数:
            arguments: 连接参数（host, port, user, password, database）。

        返回:
            包含连接状态的 ToolResult。
        """
        await self._conn.connect(**arguments)

        return ToolResult.success(
            message=f"已连接到 MySQL 服务器 {self._conn.config.host}:{self._conn.config.port}",
            data={"database": self._conn.config.database or "未选择数据库"},
        )

    async def disconnect(self, _arguments: dict[str, Any]) -> ToolResult:
        """异步断开 MySQL 数据库连接。

        参数:
            _arguments: 未使用（为保持接口一致性）。

        返回:
            包含断开状态的 ToolResult。
        """
        await self._conn.disconnect()
        return ToolResult.success(message="已断开 MySQL 连接")

    async def query(self, arguments: dict[str, Any]) -> ToolResult:
        """异步执行 SELECT 查询。

        参数:
            arguments: 包含 'query' 键的 SQL 字符串。

        返回:
            包含查询结果的 ToolResult。
        """
        query = arguments.get("query", "")
        if not query:
            return ToolResult.error("查询语句不能为空")

        results = await self._conn.execute_query(query)
        return ToolResult.success(
            message=f"查询返回 {len(results)} 行",
            data={"sql": query, "results": results, "row_count": len(results)},
        )

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        """异步执行 INSERT/UPDATE/DELETE 语句。

        参数:
            arguments: 包含 'query' 键的 SQL 字符串。

        返回:
            包含执行统计信息的 ToolResult。
        """
        query = arguments.get("query", "")
        if not query:
            return ToolResult.error("查询语句不能为空")

        result = await self._conn.execute_update(query)
        return ToolResult.success(
            message=f"影响 {result['affected_rows']} 行",
            data={"sql": query, **result},
        )

    async def list_databases(self, _arguments: dict[str, Any]) -> ToolResult:
        """异步列出所有数据库。

        参数:
            _arguments: 未使用。

        返回:
            包含数据库列表的 ToolResult。
        """
        databases = await self._conn.get_databases()
        return ToolResult.success(
            message=f"找到 {len(databases)} 个数据库",
            data={"databases": databases, "count": len(databases)},
        )

    async def list_tables(self, _arguments: dict[str, Any]) -> ToolResult:
        """异步列出当前数据库中的所有表。

        参数:
            _arguments: 未使用。

        返回:
            包含表列表的 ToolResult。
        """
        tables = await self._conn.get_tables()
        return ToolResult.success(
            message=f"找到 {len(tables)} 个表",
            data={"tables": tables, "count": len(tables)},
        )

    async def describe_table(self, arguments: dict[str, Any]) -> ToolResult:
        """异步获取表结构信息。

        参数:
            arguments: 包含 'table_name' 键。

        返回:
            包含表结构的 ToolResult。
        """
        table_name = arguments.get("table_name", "")
        if not table_name:
            return ToolResult.error("表名不能为空")

        schema = await self._conn.get_table_schema(table_name)
        return ToolResult.success(
            message=f"表 '{table_name}' 有 {len(schema)} 个字段",
            data={"table": table_name, "schema": schema},
        )
