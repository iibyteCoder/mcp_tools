"""Redis 连接配置."""

from typing import Any

from pydantic_settings import SettingsConfigDict

from mcp_base.config import BaseConfig


class RedisConfig(BaseConfig):
    """Redis 连接配置.

    所有设置均可通过 REDIS_ 前缀的环境变量覆盖
    (如 REDIS_HOST, REDIS_PORT).
    """

    model_config = SettingsConfigDict(env_prefix="REDIS_")

    host: str = "localhost"
    port: int = 6379
    username: str = ""
    password: str = ""
    db: int = 0
    connection_timeout: int = 10
    max_connections: int = 20

    def safe_info(self) -> dict[str, Any]:
        """返回遮蔽密码的连接信息字典."""
        return {
            "host": self.host,
            "port": self.port,
            "username": self.username if self.username else "(none)",
            "password": "****" if self.password else "",
            "db": self.db,
        }
