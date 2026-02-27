"""Neo4j MCP 服务器的异步工具定义。"""

from typing import Any

from mcp.types import Tool

from mcp_base.types import ToolResult
from mcp_neo4j.connection import Neo4jConnection


class Neo4jTools:
    """异步 Neo4j MCP 工具实现。

    每个方法对应一个可被 MCP 客户端调用的工具。
    所有方法均为异步以支持非阻塞 I/O 操作。
    """

    def __init__(self, connection: Neo4jConnection):
        """使用数据库连接初始化工具。

        参数:
            connection: 异步 Neo4j 连接管理器实例。
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
                name="neo4j_connect",
                description="使用指定的连接参数连接到 Neo4j 数据库",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "uri": {
                            "type": "string",
                            "description": "Neo4j 服务器 URI（默认: bolt://localhost:7687）",
                        },
                        "user": {
                            "type": "string",
                            "description": "Neo4j 用户名（默认: neo4j）",
                        },
                        "password": {
                            "type": "string",
                            "description": "Neo4j 密码",
                        },
                        "database": {
                            "type": "string",
                            "description": "数据库名称（默认: neo4j）",
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
                name="neo4j_query",
                description="在 Neo4j 数据库上执行 Cypher 只读查询（MATCH）",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "要执行的 Cypher 查询语句",
                        },
                        "parameters": {
                            "type": "object",
                            "description": "查询参数（可选）",
                        },
                    },
                    "required": ["query"],
                },
            ),
            Tool(
                name="neo4j_execute",
                description="在 Neo4j 数据库上执行写入操作（CREATE、MERGE、DELETE、SET）",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "要执行的 Cypher 写入语句",
                        },
                        "parameters": {
                            "type": "object",
                            "description": "查询参数（可选）",
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

    async def connect(self, arguments: dict[str, Any]) -> ToolResult:
        """异步连接到 Neo4j 数据库。

        参数:
            arguments: 连接参数（uri, user, password, database）。

        返回:
            包含连接状态的 ToolResult。
        """
        await self._conn.connect(**arguments)

        return ToolResult.success(
            message=f"已连接到 Neo4j 服务器 {self._conn.config.uri}",
            data={"database": self._conn.config.database},
        )

    async def disconnect(self, _arguments: dict[str, Any]) -> ToolResult:
        """异步断开 Neo4j 数据库连接。

        参数:
            _arguments: 未使用（为保持接口一致性）。

        返回:
            包含断开状态的 ToolResult。
        """
        await self._conn.disconnect()
        return ToolResult.success(message="已断开 Neo4j 连接")

    async def query(self, arguments: dict[str, Any]) -> ToolResult:
        """异步执行 Cypher 查询。

        参数:
            arguments: 包含 'query' 键的 Cypher 字符串和可选的 'parameters'。

        返回:
            包含查询结果的 ToolResult。
        """
        query = arguments.get("query", "")
        if not query:
            return ToolResult.error("查询语句不能为空")

        parameters = arguments.get("parameters")
        results = await self._conn.execute_query(query, parameters)
        return ToolResult.success(
            message=f"查询返回 {len(results)} 条记录",
            data={"cypher": query, "parameters": parameters, "results": results, "record_count": len(results)},
        )

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        """异步执行写入查询。

        参数:
            arguments: 包含 'query' 键的 Cypher 字符串和可选的 'parameters'。

        返回:
            包含执行统计信息的 ToolResult。
        """
        query = arguments.get("query", "")
        if not query:
            return ToolResult.error("查询语句不能为空")

        parameters = arguments.get("parameters")
        result = await self._conn.execute_write(query, parameters)
        return ToolResult.success(
            message="查询执行成功",
            data={"cypher": query, "parameters": parameters, **result},
        )

    async def list_labels(self, _arguments: dict[str, Any]) -> ToolResult:
        """异步列出所有节点标签。

        参数:
            _arguments: 未使用。

        返回:
            包含标签列表的 ToolResult。
        """
        labels = await self._conn.get_labels()
        return ToolResult.success(
            message=f"找到 {len(labels)} 个标签",
            data={"labels": labels, "count": len(labels)},
        )

    async def list_relationship_types(self, _arguments: dict[str, Any]) -> ToolResult:
        """异步列出所有关系类型。

        参数:
            _arguments: 未使用。

        返回:
            包含关系类型列表的 ToolResult。
        """
        rel_types = await self._conn.get_relationship_types()
        return ToolResult.success(
            message=f"找到 {len(rel_types)} 种关系类型",
            data={"relationship_types": rel_types, "count": len(rel_types)},
        )

    async def list_properties(self, _arguments: dict[str, Any]) -> ToolResult:
        """异步列出所有属性键。

        参数:
            _arguments: 未使用。

        返回:
            包含属性键列表的 ToolResult。
        """
        properties = await self._conn.get_property_keys()
        return ToolResult.success(
            message=f"找到 {len(properties)} 个属性键",
            data={"properties": properties, "count": len(properties)},
        )

    async def describe_label(self, arguments: dict[str, Any]) -> ToolResult:
        """异步获取节点标签结构。

        参数:
            arguments: 包含 'label' 键。

        返回:
            包含标签结构的 ToolResult。
        """
        label = arguments.get("label", "")
        if not label:
            return ToolResult.error("标签名不能为空")

        schema = await self._conn.get_node_schema(label)
        return ToolResult.success(
            message=f"标签 '{label}' 有 {len(schema)} 个属性",
            data={"label": label, "schema": schema},
        )
