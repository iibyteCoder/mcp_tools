"""Neo4j MCP 服务器的异步工具定义."""

from typing import Any

from mcp.types import Tool

from mcp_base.types import PaginationParams, ToolResult
from mcp_neo4j.connection import Neo4jConnection


class Neo4jTools:
    """异步 Neo4j MCP 工具实现.

    每个方法对应一个可被 MCP 客户端调用的工具.
    所有方法均为异步以支持非阻塞 I/O 操作.
    """

    def __init__(self, connection: Neo4jConnection):
        self._conn = connection

    @staticmethod
    def get_tool_definitions() -> list[Tool]:
        """返回所有工具定义用于注册."""
        return [
            Tool(
                name="neo4j_connect",
                description="使用指定的连接参数连接到 Neo4j 数据库",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "uri": {
                            "type": "string",
                            "description": "Neo4j 服务器 URI (默认: bolt://localhost:7687)",
                        },
                        "user": {
                            "type": "string",
                            "description": "Neo4j 用户名 (默认: neo4j)",
                        },
                        "password": {
                            "type": "string",
                            "description": "Neo4j 密码",
                        },
                        "database": {
                            "type": "string",
                            "description": "数据库名称 (默认: neo4j)",
                        },
                    },
                    "required": [],
                },
            ),
            Tool(
                name="neo4j_disconnect",
                description="断开当前 Neo4j 数据库连接",
                inputSchema={"type": "object", "properties": {}},
            ),
            Tool(
                name="neo4j_status",
                description="获取 Neo4j 连接状态, 服务器版本和连接池信息",
                inputSchema={"type": "object", "properties": {}},
            ),
            Tool(
                name="neo4j_query",
                description=(
                    "在 Neo4j 上执行 Cypher 只读查询 (MATCH). "
                    "结果自动分页 (默认每页 50 行). "
                    "page: 页码, 从 1 开始; page_size: 每页行数 (1~500, 默认 50). "
                    "当 has_more=true 时表示还有更多数据, 传入 page+1 获取下一页."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "要执行的 Cypher 查询语句",
                        },
                        "parameters": {
                            "type": "object",
                            "description": "查询参数 (可选)",
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
                name="neo4j_execute",
                description="在 Neo4j 数据库上执行写入操作 (CREATE, MERGE, DELETE, SET)",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "要执行的 Cypher 写入语句",
                        },
                        "parameters": {
                            "type": "object",
                            "description": "查询参数 (可选)",
                        },
                    },
                    "required": ["query"],
                },
            ),
            Tool(
                name="neo4j_list_labels",
                description="列出数据库中所有节点标签",
                inputSchema={"type": "object", "properties": {}},
            ),
            Tool(
                name="neo4j_list_relationship_types",
                description="列出数据库中所有关系类型",
                inputSchema={"type": "object", "properties": {}},
            ),
            Tool(
                name="neo4j_list_properties",
                description="列出数据库中所有属性键",
                inputSchema={"type": "object", "properties": {}},
            ),
            Tool(
                name="neo4j_describe_label",
                description="获取指定标签的节点属性结构",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "label": {
                            "type": "string",
                            "description": "要查看的节点标签",
                        },
                    },
                    "required": ["label"],
                },
            ),
        ]

    # ── 连接管理 ──

    async def connect(self, arguments: dict[str, Any]) -> ToolResult:
        """连接到 Neo4j 数据库."""
        await self._conn.connect(**arguments)
        return ToolResult.success(
            message=f"已连接到 Neo4j 服务器 {self._conn.config.uri}",
            data={"database": self._conn.config.database},
        )

    async def disconnect(self, _arguments: dict[str, Any]) -> ToolResult:
        """断开 Neo4j 数据库连接."""
        await self._conn.disconnect()
        return ToolResult.success(message="已断开 Neo4j 连接")

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
            message="Neo4j 已连接" if connected else "Neo4j 未连接",
            data=data,
        )

    # ── 查询执行 ──

    async def query(self, arguments: dict[str, Any]) -> ToolResult:
        """执行分页 Cypher 查询."""
        query = arguments.get("query", "")
        if not query:
            return ToolResult.error("查询语句不能为空")

        parameters = arguments.get("parameters")
        pag = PaginationParams.from_args(arguments)

        results = await self._conn.execute_query(
            query,
            parameters,
            skip=pag.offset,
            limit=pag.fetch_limit,
        )

        has_more = len(results) > pag.page_size
        rows = results[: pag.page_size]

        if has_more:
            message = f"第 {pag.page} 页, 返回 {len(rows)} 条记录, 还有更多数据. 传入 page={pag.page + 1} 获取下一页"
        else:
            message = f"第 {pag.page} 页, 返回 {len(rows)} 条记录, 已无更多数据"

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
        """执行写入查询."""
        query = arguments.get("query", "")
        if not query:
            return ToolResult.error("查询语句不能为空")

        parameters = arguments.get("parameters")
        result = await self._conn.execute_write(query, parameters)
        return ToolResult.success(
            message="查询执行成功",
            data={"cypher": query, "parameters": parameters, **result},
        )

    # ── Schema 查询 ──

    async def list_labels(self, _arguments: dict[str, Any]) -> ToolResult:
        """列出所有节点标签."""
        labels = await self._conn.get_labels()
        return ToolResult.success(
            message=f"找到 {len(labels)} 个标签",
            data={"labels": labels, "count": len(labels)},
        )

    async def list_relationship_types(self, _arguments: dict[str, Any]) -> ToolResult:
        """列出所有关系类型."""
        rel_types = await self._conn.get_relationship_types()
        return ToolResult.success(
            message=f"找到 {len(rel_types)} 种关系类型",
            data={"relationship_types": rel_types, "count": len(rel_types)},
        )

    async def list_properties(self, _arguments: dict[str, Any]) -> ToolResult:
        """列出所有属性键."""
        properties = await self._conn.get_property_keys()
        return ToolResult.success(
            message=f"找到 {len(properties)} 个属性键",
            data={"properties": properties, "count": len(properties)},
        )

    async def describe_label(self, arguments: dict[str, Any]) -> ToolResult:
        """获取节点标签结构."""
        label = arguments.get("label", "")
        if not label:
            return ToolResult.error("标签名不能为空")

        schema = await self._conn.get_node_schema(label)
        return ToolResult.success(
            message=f"标签 '{label}' 有 {len(schema)} 个属性",
            data={"label": label, "schema": schema},
        )
