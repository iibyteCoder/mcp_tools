"""查询操作工具 — neo4j_query / neo4j_execute."""

from collections.abc import Callable
from typing import Any

from mcp.types import Tool

from mcp_base.types import PaginationParams, ToolResult
from mcp_neo4j.connection import Neo4jConnection


def get_definitions() -> list[Tool]:
    return [
        Tool(
            name="neo4j_query",
            description=(
                "执行 Cypher 只读查询(MATCH), 结果自动分页(默认每页 50 行). "
                "page 从 1 开始, page_size 1~500. parameters 为可选的查询参数映射. "
                "has_more=true 时传入 page+1 获取下一页"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Cypher 查询语句"},
                    "parameters": {"type": "object", "description": "查询参数映射 (可选)"},
                    "page": {"type": "integer", "description": "页码, 1 开始 (默认 1)"},
                    "page_size": {"type": "integer", "description": "每页行数 1~500 (默认 50)"},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="neo4j_execute",
            description="执行 Cypher 写入操作(CREATE/MERGE/DELETE/SET), 返回影响计数(节点/关系/属性)",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Cypher 写入语句"},
                    "parameters": {"type": "object", "description": "查询参数映射 (可选)"},
                },
                "required": ["query"],
            },
        ),
    ]


def build_handlers(conn: Neo4jConnection) -> dict[str, Callable[[dict[str, Any]], Any]]:
    h = _QueryHandlers(conn)
    return {"neo4j_query": h.query, "neo4j_execute": h.execute}


class _QueryHandlers:
    def __init__(self, conn: Neo4jConnection):
        self._conn = conn

    async def query(self, args: dict[str, Any]) -> ToolResult:
        sql = args["query"]
        if not sql.strip():
            return ToolResult.error("查询语句不能为空")

        parameters = args.get("parameters")
        pag = PaginationParams.from_args(args)

        results = await self._conn.execute_query(sql, parameters, skip=pag.offset, limit=pag.fetch_limit)

        has_more = len(results) > pag.page_size
        rows = results[: pag.page_size]

        data: dict[str, Any] = {
            "rows": rows, "page": pag.page, "page_size": pag.page_size, "has_more": has_more,
        }
        if has_more:
            data["next_page"] = pag.page + 1

        return ToolResult.success(data=data)

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        sql = args["query"]
        if not sql.strip():
            return ToolResult.error("查询语句不能为空")

        parameters = args.get("parameters")
        result = await self._conn.execute_write(sql, parameters)
        return ToolResult.success(data={"cypher": sql, "parameters": parameters, **result})
