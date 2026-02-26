"""Neo4j connection configuration."""

from mcp_base.config import BaseConfig


class Neo4jConfig(BaseConfig):
    """Neo4j connection configuration.

    All settings can be overridden via environment variables
    with the prefix NEO4J_ (e.g., NEO4J_URI, NEO4J_USER).
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
