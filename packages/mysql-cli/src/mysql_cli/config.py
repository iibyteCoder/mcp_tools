"""Immutable MySQL connection configuration and precedence rules."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any
from urllib.parse import unquote, urlparse

from mcp_mysql.config import MySQLConfig


@dataclass(frozen=True)
class MySQLConnectionOptions:
    host: str
    port: int
    user: str
    password: str
    database: str
    charset: str
    connection_timeout: int

    @classmethod
    def from_environment(cls) -> MySQLConnectionOptions:
        settings = MySQLConfig()
        return cls(
            settings.host,
            settings.port,
            settings.user,
            settings.password,
            settings.database,
            settings.charset,
            settings.connection_timeout,
        )

    def apply_url(self, value: str) -> MySQLConnectionOptions:
        parsed = urlparse(value)
        if parsed.scheme != "mysql" or not parsed.hostname:
            raise ValueError("MySQL URL 必须形如 mysql://user:password@host:port/database")
        return replace(
            self,
            host=parsed.hostname,
            port=parsed.port or MySQLConfig.model_fields["port"].default,
            user=unquote(parsed.username or MySQLConfig.model_fields["user"].default),
            password=unquote(parsed.password or ""),
            database=unquote(parsed.path.strip("/")),
        )

    def apply_overrides(self, **values: Any) -> MySQLConnectionOptions:
        defined_values = {name: value for name, value in values.items() if value is not None}
        return replace(self, **defined_values)

    def connection_arguments(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "port": self.port,
            "user": self.user,
            "password": self.password,
            "database": self.database,
            "charset": self.charset,
            "connection_timeout": self.connection_timeout,
        }

    def profile_settings(self) -> dict[str, Any]:
        return self.connection_arguments()

    def safe_info(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "port": self.port,
            "user": self.user,
            "password": "****" if self.password else "",
            "database": self.database or "(none)",
            "charset": self.charset,
            "connection_timeout": self.connection_timeout,
        }
