"""MySQL 连接配置。"""

from mcp_base.config import BaseConfig


class MySQLConfig(BaseConfig):
    """MySQL 连接配置。

    所有设置均可通过 MYSQL_ 前缀的环境变量覆盖
    （如 MYSQL_HOST、MYSQL_PORT）。
    """

    host: str = "localhost"
    port: int = 3306
    user: str = "root"
    password: str = ""
    database: str = ""
    charset: str = "utf8mb4"
    collation: str = "utf8mb4_unicode_ci"
    autocommit: bool = True
    connection_timeout: int = 10

    class Config:
        env_prefix = "MYSQL_"
