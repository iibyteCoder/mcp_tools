"""MySQL connection configuration."""

from mcp_base.config import BaseConfig


class MySQLConfig(BaseConfig):
    """MySQL connection configuration.

    All settings can be overridden via environment variables
    with the prefix MYSQL_ (e.g., MYSQL_HOST, MYSQL_PORT).
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
