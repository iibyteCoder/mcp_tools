"""查询操作工具 — mysql_query / mysql_execute."""

from collections.abc import Callable
from typing import Any

from mcp.types import Tool

from mcp_base.types import PaginationParams, ToolResult
from mcp_mysql.connection import MySQLConnection


def get_definitions() -> list[Tool]:
    return [
        Tool(
            name="mysql_query",
            description=(
                "执行 SELECT 查询, 结果自动分页(默认每页 50 行). "
                "page 从 1 开始, page_size 1~500. has_more=true 时传入 page+1 获取下一页"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "SELECT 查询语句"},
                    "page": {"type": "integer", "description": "页码, 1 开始 (默认 1)"},
                    "page_size": {"type": "integer", "description": "每页行数 1~500 (默认 50)"},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="mysql_execute",
            description="执行 INSERT/UPDATE/DELETE 语句, 返回影响行数和插入 ID",
            inputSchema={
                "type": "object",
                "properties": {"query": {"type": "string", "description": "写入 SQL 语句"}},
                "required": ["query"],
            },
        ),
    ]


def build_handlers(conn: MySQLConnection) -> dict[str, Callable[[dict[str, Any]], Any]]:
    h = _QueryHandlers(conn)
    return {"mysql_query": h.query, "mysql_execute": h.execute}


class _QueryHandlers:
    def __init__(self, conn: MySQLConnection):
        self._conn = conn

    async def query(self, args: dict[str, Any]) -> ToolResult:
        sql = args["query"]
        if not sql.strip():
            return ToolResult.error("查询语句不能为空")

        pag = PaginationParams.from_args(args)
        results = await self._conn.execute_query(sql, skip=pag.offset, limit=pag.fetch_limit)

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

        result = await self._conn.execute_update(sql)
        return ToolResult.success(data={"sql": sql, **result})
