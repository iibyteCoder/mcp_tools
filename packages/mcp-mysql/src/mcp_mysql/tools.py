"""MySQL MCP 服务器的异步工具定义."""

from typing import Any

from mcp.types import Tool

from mcp_base.types import PaginationParams, ToolResult
from mcp_mysql.connection import MySQLConnection


class MySQLTools:
    """异步 MySQL MCP 工具实现.

    每个方法对应一个可被 MCP 客户端调用的工具.
    所有方法均为异步以支持非阻塞 I/O 操作.
    """

    def __init__(self, connection: MySQLConnection):
        self._conn = connection

    @staticmethod
    def get_tool_definitions() -> list[Tool]:
        """返回所有工具定义用于注册."""
        return [
            Tool(
                name="mysql_connect",
                description="使用指定的连接参数连接到 MySQL 数据库",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "host": {
                            "type": "string",
                            "description": "MySQL 服务器地址 (默认: localhost)",
                        },
                        "port": {
                            "type": "integer",
                            "description": "MySQL 服务器端口 (默认: 3306)",
                        },
                        "user": {
                            "type": "string",
                            "description": "MySQL 用户名 (默认: root)",
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
                name="mysql_status",
                description="获取 MySQL 连接状态, 服务器版本和连接池信息",
                inputSchema={"type": "object", "properties": {}},
            ),
            Tool(
                name="mysql_query",
                description=(
                    "在 MySQL 上执行 SELECT 查询. "
                    "结果自动分页 (默认每页 50 行). "
                    "page: 页码, 从 1 开始; page_size: 每页行数 (1~500, 默认 50). "
                    "当 has_more=true 时表示还有更多数据, 传入 page+1 获取下一页."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "要执行的 SELECT SQL 查询语句",
                        },
                        "page": {
                            "type": "integer",
                            "description": "页码, 从 1 开始 (默认: 1)",
                        },
                        "page_size": {
                            "type": "integer",
                            "description": "每页行数, 1~500 (默认: 50)",
                        },
                    },
                    "required": ["query"],
                },
            ),
            Tool(
                name="mysql_execute",
                description="在 MySQL 数据库上执行 INSERT, UPDATE 或 DELETE 语句",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "要执行的 SQL 语句 (INSERT/UPDATE/DELETE)",
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

    # ── 连接管理 ──

    async def connect(self, arguments: dict[str, Any]) -> ToolResult:
        """连接到 MySQL 数据库."""
        await self._conn.connect(**arguments)
        return ToolResult.success(
            message=f"已连接到 MySQL 服务器 {self._conn.config.host}:{self._conn.config.port}",
            data={"database": self._conn.config.database or "(none)"},
        )

    async def disconnect(self, _arguments: dict[str, Any]) -> ToolResult:
        """断开 MySQL 数据库连接."""
        await self._conn.disconnect()
        return ToolResult.success(message="已断开 MySQL 连接")

    # ── 状态诊断 ──

    async def status(self, _arguments: dict[str, Any]) -> ToolResult:
        """获取连接状态, 服务器版本和连接池信息."""
        connected = self._conn.is_connected
        data: dict[str, Any] = {
            "connected": connected,
            "config": self._conn.config.safe_info(),
        }

        if connected:
            data["server_info"] = await self._conn.get_server_info()
            data["pool_status"] = self._conn.get_pool_status()

        return ToolResult.success(
            message="MySQL 已连接" if connected else "MySQL 未连接",
            data=data,
        )

    # ── 查询执行 ──

    async def query(self, arguments: dict[str, Any]) -> ToolResult:
        """执行分页 SELECT 查询."""
        query = arguments.get("query", "")
        if not query:
            return ToolResult.error("查询语句不能为空")

        pag = PaginationParams.from_args(arguments)

        results = await self._conn.execute_query(
            query,
            skip=pag.offset,
            limit=pag.fetch_limit,
        )

        has_more = len(results) > pag.page_size
        rows = results[: pag.page_size]

        if has_more:
            message = f"第 {pag.page} 页, 返回 {len(rows)} 行, 还有更多数据. 传入 page={pag.page + 1} 获取下一页"
        else:
            message = f"第 {pag.page} 页, 返回 {len(rows)} 行, 已无更多数据"

        data: dict[str, Any] = {
            "rows": rows,
            "page": pag.page,
            "page_size": pag.page_size,
            "has_more": has_more,
        }
        if has_more:
            data["next_page"] = pag.page + 1

        return ToolResult.success(message=message, data=data)

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        """执行 INSERT/UPDATE/DELETE 语句."""
        query = arguments.get("query", "")
        if not query:
            return ToolResult.error("查询语句不能为空")

        result = await self._conn.execute_update(query)
        return ToolResult.success(
            message=f"影响 {result['affected_rows']} 行",
            data={"sql": query, **result},
        )

    # ── Schema 查询 ──

    async def list_databases(self, _arguments: dict[str, Any]) -> ToolResult:
        """列出所有数据库."""
        databases = await self._conn.get_databases()
        return ToolResult.success(
            message=f"找到 {len(databases)} 个数据库",
            data={"databases": databases, "count": len(databases)},
        )

    async def list_tables(self, _arguments: dict[str, Any]) -> ToolResult:
        """列出当前数据库中的所有表."""
        tables = await self._conn.get_tables()
        return ToolResult.success(
            message=f"找到 {len(tables)} 个表",
            data={"tables": tables, "count": len(tables)},
        )

    async def describe_table(self, arguments: dict[str, Any]) -> ToolResult:
        """获取表结构信息."""
        table_name = arguments.get("table_name", "")
        if not table_name:
            return ToolResult.error("表名不能为空")

        schema = await self._conn.get_table_schema(table_name)
        return ToolResult.success(
            message=f"表 '{table_name}' 有 {len(schema)} 个字段",
            data={"table": table_name, "schema": schema},
        )
