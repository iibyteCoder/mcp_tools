"""Concrete database adapters."""

from mysql_client.adapters.aiomysql import AiomysqlDriverFactory

__all__ = ["AiomysqlDriverFactory"]
