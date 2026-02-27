"""Neo4j 连接配置。"""

from mcp_base.config import BaseConfig


class Neo4jConfig(BaseConfig):
    """Neo4j 连接配置。

    所有设置均可通过 NEO4J_ 前缀的环境变量覆盖
    （如 NEO4J_URI、NEO4J_USER）。
    """

    uri: str = "bolt://localhost:7687"
    user: str = "neo4j"
    password: str = ""
    database: str = "neo4j"
    max_connection_lifetime: int = 3600
    max_connection_pool_size: int = 50
    connection_timeout: int = 30

    class Config:
        env_prefix = "NEO4J_"
