"""MCP 服务器类型定义。"""

from dataclasses import dataclass
from enum import Enum
from typing import Any


class ToolStatus(str, Enum):
    """工具执行状态。"""

    SUCCESS = "success"
    ERROR = "error"


@dataclass
class ToolResult:
    """工具执行的标准结果格式。"""

    status: ToolStatus
    message: str = ""
    data: Any = None

    def to_dict(self) -> dict[str, Any]:
        """转换为字典以便 JSON 序列化。"""
        result: dict[str, Any] = {"status": self.status.value}
        if self.message:
            result["message"] = self.message
        if self.data is not None:
            result["data"] = self.data
        return result

    @classmethod
    def success(cls, message: str = "", data: Any = None) -> "ToolResult":
        """创建成功结果。"""
        return cls(status=ToolStatus.SUCCESS, message=message, data=data)

    @classmethod
    def error(cls, message: str) -> "ToolResult":
        """创建错误结果。"""
        return cls(status=ToolStatus.ERROR, message=message)
