"""Schema 查询工具 — neo4j_list_labels / list_relationship_types / list_properties / describe_label."""

from collections.abc import Callable
from typing import Any

from mcp.types import Tool

from mcp_base.types import ToolResult
from mcp_neo4j.connection import Neo4jConnection


def get_definitions() -> list[Tool]:
    return [
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
            description="获取指定标签节点的属性结构(采样 100 条记录推断)",
            inputSchema={
                "type": "object",
                "properties": {"label": {"type": "string", "description": "节点标签名"}},
                "required": ["label"],
            },
        ),
    ]


def build_handlers(conn: Neo4jConnection) -> dict[str, Callable[[dict[str, Any]], Any]]:
    h = _SchemaHandlers(conn)
    return {
        "neo4j_list_labels": h.list_labels,
        "neo4j_list_relationship_types": h.list_relationship_types,
        "neo4j_list_properties": h.list_properties,
        "neo4j_describe_label": h.describe_label,
    }


class _SchemaHandlers:
    def __init__(self, conn: Neo4jConnection):
        self._conn = conn

    async def list_labels(self, _args: dict[str, Any]) -> ToolResult:
        labels = await self._conn.get_labels()
        return ToolResult.success(data={"labels": labels, "count": len(labels)})

    async def list_relationship_types(self, _args: dict[str, Any]) -> ToolResult:
        rel_types = await self._conn.get_relationship_types()
        return ToolResult.success(data={"relationship_types": rel_types, "count": len(rel_types)})

    async def list_properties(self, _args: dict[str, Any]) -> ToolResult:
        properties = await self._conn.get_property_keys()
        return ToolResult.success(data={"properties": properties, "count": len(properties)})

    async def describe_label(self, args: dict[str, Any]) -> ToolResult:
        label = args["label"]
        if not label.strip():
            return ToolResult.error("标签名不能为空")
        schema = await self._conn.get_node_schema(label)
        return ToolResult.success(data={"label": label, "schema": schema, "field_count": len(schema)})
