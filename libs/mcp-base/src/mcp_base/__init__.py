"""MCP Base - MCP 服务器共享工具库。"""

from mcp_base.config import BaseConfig
from mcp_base.server import BaseMCPServer
from mcp_base.types import ToolResult

__all__ = ["BaseConfig", "BaseMCPServer", "ToolResult"]
__version__ = "0.1.0"
