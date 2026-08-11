"""MinIO 工具聚合 — 按职责拆分, 各模块自含定义与处理器."""

from collections.abc import Callable
from typing import Any

from mcp.types import Tool

from mcp_minio.connection import MinioConnection

from . import bucket, connection, object

_Handler = Callable[[dict[str, Any]], Any]

_MODULES = (connection, bucket, object)


def get_all_definitions() -> list[Tool]:
    tools: list[Tool] = []
    for mod in _MODULES:
        tools.extend(mod.get_definitions())
    return tools


def build_dispatch(conn: MinioConnection) -> dict[str, _Handler]:
    dispatch: dict[str, _Handler] = {}
    for mod in _MODULES:
        dispatch.update(mod.build_handlers(conn))
    return dispatch
