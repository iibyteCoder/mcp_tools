"""Type definitions for MCP servers."""

from dataclasses import dataclass
from enum import Enum
from typing import Any


class ToolStatus(str, Enum):
    """Status of tool execution."""

    SUCCESS = "success"
    ERROR = "error"


@dataclass
class ToolResult:
    """Standard result format for tool execution."""

    status: ToolStatus
    message: str = ""
    data: Any = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result: dict[str, Any] = {"status": self.status.value}
        if self.message:
            result["message"] = self.message
        if self.data is not None:
            result["data"] = self.data
        return result

    @classmethod
    def success(cls, message: str = "", data: Any = None) -> "ToolResult":
        """Create a success result."""
        return cls(status=ToolStatus.SUCCESS, message=message, data=data)

    @classmethod
    def error(cls, message: str) -> "ToolResult":
        """Create an error result."""
        return cls(status=ToolStatus.ERROR, message=message)
