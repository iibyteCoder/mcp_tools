"""异步 MinIO MCP 服务器实现."""

from typing import Any

from mcp.types import Tool

from mcp_base.server import BaseMCPServer
from mcp_base.types import ToolResult
from mcp_minio.config import MinioConfig
from mcp_minio.connection import MinioConnection
from mcp_minio.tools import build_dispatch, get_all_definitions


class MinioServer(BaseMCPServer):
    """异步 MinIO 对象存储操作 MCP 服务器.

    提供工具:
    - 连接管理: minio_connect / disconnect / status
    - Bucket: minio_list_buckets / bucket_exists / make_bucket / remove_bucket
    - Object: minio_put_object / get_object / remove_object / list_objects / stat_object / copy_object
    - Presigned: minio_presigned_get_url / presigned_put_url
    """

    def __init__(self, config: MinioConfig | None = None):
        super().__init__(name="mcp-minio", version="0.1.0")
        self._config = config or MinioConfig()
        self._connection = MinioConnection(self._config)
        self._dispatch = build_dispatch(self._connection)

    async def list_tools(self) -> list[Tool]:
        return get_all_definitions()

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        handler = self._dispatch.get(name)
        if handler is None:
            return ToolResult.error(f"未知工具: {name}")
        return await handler(arguments)
