"""Immutable Redis connection configuration and precedence rules."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any
from urllib.parse import unquote, urlparse

from mcp_redis.config import RedisConfig


@dataclass(frozen=True)
class RedisConnectionOptions:
    host: str
    port: int
    username: str
    password: str
    database: int
    connection_timeout: int

    @classmethod
    def from_environment(cls) -> RedisConnectionOptions:
        settings = RedisConfig()
        return cls(
            settings.host,
            settings.port,
            settings.username,
            settings.password,
            settings.db,
            settings.connection_timeout,
        )

    def apply_url(self, value: str) -> RedisConnectionOptions:
        parsed = urlparse(value)
        if parsed.scheme != "redis" or not parsed.hostname:
            raise ValueError("Redis URL 必须形如 redis://[user:password@]host:port/db")
        database_path = parsed.path.strip("/")
        return replace(
            self,
            host=parsed.hostname,
            port=parsed.port or RedisConfig.model_fields["port"].default,
            username=unquote(parsed.username or ""),
            password=unquote(parsed.password or ""),
            database=int(database_path) if database_path else 0,
        )

    def apply_overrides(self, **values: Any) -> RedisConnectionOptions:
        defined_values = {name: value for name, value in values.items() if value is not None}
        return replace(self, **defined_values)

    def connection_arguments(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "port": self.port,
            "username": self.username,
            "password": self.password,
            "db": self.database,
            "connection_timeout": self.connection_timeout,
        }

    def profile_settings(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "port": self.port,
            "username": self.username,
            "password": self.password,
            "database": self.database,
            "connection_timeout": self.connection_timeout,
        }

    def safe_info(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "port": self.port,
            "username": self.username or "(none)",
            "password": "****" if self.password else "",
            "database": self.database,
            "connection_timeout": self.connection_timeout,
        }
