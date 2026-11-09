"""Validated, secret-safe connection configuration for one DM session."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dm_client.domain.values import SchemaName

DEFAULT_DM_PORT = 5236
DEFAULT_LOGIN_TIMEOUT_SECONDS = 5.0
DEFAULT_QUERY_TIMEOUT_SECONDS = 0.0
DEFAULT_FETCH_SIZE = 1000


@dataclass(frozen=True, slots=True, kw_only=True)
class SecretValue:
    """A secret that cannot be exposed by normal string conversion or repr."""

    _value: str = field(repr=False)

    def __post_init__(self) -> None:
        if not self._value:
            raise ValueError("secret value must not be empty")

    def __repr__(self) -> str:
        return "SecretValue(<redacted>)"

    def __str__(self) -> str:
        return "<redacted>"

    def reveal(self) -> str:
        """Return the secret only for the driver adapter boundary."""

        return self._value


@dataclass(frozen=True, slots=True, kw_only=True)
class DmConnectionConfig:
    """All settings needed to open one non-pooled DM connection."""

    host: str
    user: str
    password: SecretValue
    port: int = DEFAULT_DM_PORT
    schema: SchemaName | None = None
    connect_timeout_seconds: float = DEFAULT_LOGIN_TIMEOUT_SECONDS
    query_timeout_seconds: float = DEFAULT_QUERY_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        if not self.host.strip():
            raise ValueError("DM host must not be empty")
        if not self.user.strip():
            raise ValueError("DM user must not be empty")
        if isinstance(self.port, bool) or not 1 <= self.port <= 65_535:
            raise ValueError("DM port must be between 1 and 65535")
        if not math.isfinite(self.connect_timeout_seconds) or self.connect_timeout_seconds <= 0:
            raise ValueError("connect timeout must be greater than zero")
        if not math.isfinite(self.query_timeout_seconds) or self.query_timeout_seconds < 0:
            raise ValueError("query timeout must be zero or greater")


__all__ = [
    "DEFAULT_DM_PORT",
    "DEFAULT_FETCH_SIZE",
    "DEFAULT_LOGIN_TIMEOUT_SECONDS",
    "DEFAULT_QUERY_TIMEOUT_SECONDS",
    "DmConnectionConfig",
    "SecretValue",
]
