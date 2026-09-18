"""CLI error seam for backend operations."""

from collections.abc import Callable

from db_cli_core.errors import error_result
from mcp_base.types import ToolResult


def execute_safely(operation: Callable[[], ToolResult]) -> ToolResult:
    try:
        return operation()
    except Exception as exc:
        return error_result(exc)
