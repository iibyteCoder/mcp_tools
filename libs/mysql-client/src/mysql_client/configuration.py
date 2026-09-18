"""Compatibility imports for connection configuration models."""

from mysql_client.domain.configuration import (
    DEFAULT_CONNECT_TIMEOUT_SECONDS,
    DEFAULT_MYSQL_CHARSET,
    DEFAULT_MYSQL_PORT,
    DEFAULT_READ_TIMEOUT_SECONDS,
    MySqlConnectionConfig,
    SecretValue,
)

__all__ = [
    "DEFAULT_CONNECT_TIMEOUT_SECONDS",
    "DEFAULT_MYSQL_CHARSET",
    "DEFAULT_MYSQL_PORT",
    "DEFAULT_READ_TIMEOUT_SECONDS",
    "MySqlConnectionConfig",
    "SecretValue",
]
