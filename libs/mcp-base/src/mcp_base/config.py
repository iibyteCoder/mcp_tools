"""MCP 服务器配置管理。"""

from abc import ABC
from typing import Any

from pydantic_settings import BaseSettings


class BaseConfig(BaseSettings, ABC):
    """MCP 服务器配置基类。

    子类应定义特定的配置字段。
    所有字段均可通过环境变量覆盖。
    """

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

    def to_connection_params(self) -> dict[str, Any]:
        """将配置转换为连接参数。

        子类可重写此方法以提供特定于连接的参数。
        """
        return self.model_dump(exclude_none=True)
