"""MCP 服务器类型定义。"""

from dataclasses import dataclass
from enum import Enum
from typing import Any

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 500


class ToolStatus(str, Enum):
    """工具执行状态。"""

    SUCCESS = "success"
    ERROR = "error"


@dataclass
class PaginationParams:
    """分页参数, 负责参数解析和边界约束."""

    page: int = 1
    page_size: int = DEFAULT_PAGE_SIZE

    @classmethod
    def from_args(cls, arguments: dict[str, Any]) -> "PaginationParams":
        """从工具参数中解析并约束分页参数。"""
        page = max(arguments.get("page", 1), 1)
        page_size = min(max(arguments.get("page_size", DEFAULT_PAGE_SIZE), 1), MAX_PAGE_SIZE)
        return cls(page=page, page_size=page_size)

    @property
    def fetch_limit(self) -> int:
        """内部获取量 = page_size + 1, N+1 策略检测是否有下一页."""
        return self.page_size + 1

    @property
    def offset(self) -> int:
        """跳过的记录数。"""
        return (self.page - 1) * self.page_size


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
