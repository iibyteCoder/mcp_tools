"""MySQL 连接配置."""

from typing import Any

from pydantic_settings import SettingsConfigDict

from mcp_base.config import BaseConfig


class MySQLConfig(BaseConfig):
    """MySQL 连接配置.

    所有设置均可通过 MYSQL_ 前缀的环境变量覆盖
    (如 MYSQL_HOST, MYSQL_PORT).
    """

    model_config = SettingsConfigDict(env_prefix="MYSQL_")

    host: str = "localhost"
    port: int = 3306
    user: str = "root"
    password: str = ""
    database: str = ""
    charset: str = "utf8mb4"
    collation: str = "utf8mb4_unicode_ci"
    autocommit: bool = True
    connection_timeout: int = 10

    def safe_info(self) -> dict[str, Any]:
        """返回遮蔽密码的连接信息字典."""
        return {
            "host": self.host,
            "port": self.port,
            "user": self.user,
            "password": "****" if self.password else "",
            "database": self.database or "(none)",
            "charset": self.charset,
        }
