"""Validated, secret-safe connection configuration for one MySQL session."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True, kw_only=True)
class SecretValue:
    """A secret that cannot be exposed by normal string conversion or repr."""

    _value: str = field(repr=False)

    def __post_init__(self) -> None:
        if not self._value:
            raise ValueError("敏感值不能为空")

    def __repr__(self) -> str:
        return "SecretValue(<redacted>)"

    def __str__(self) -> str:
        return "<redacted>"

    def reveal(self) -> str:
        """Return the secret only for the driver adapter boundary."""

        return self._value


@dataclass(frozen=True, slots=True, kw_only=True)
class MySqlConnectionConfig:
    """All settings needed to open one non-pooled MySQL connection."""

    host: str
    user: str
    password: SecretValue
    port: int = 3306
    database: str | None = None
    charset: str = "utf8mb4"
    connect_timeout_seconds: float = 10.0
    read_timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        if not self.host.strip():
            raise ValueError("MySQL host 不能为空")
        if not self.user.strip():
            raise ValueError("MySQL user 不能为空")
        if not 1 <= self.port <= 65_535:
            raise ValueError("MySQL port 必须在 1 到 65535 之间")
        if not self.charset.strip():
            raise ValueError("MySQL charset 不能为空")
        if self.connect_timeout_seconds <= 0:
            raise ValueError("连接超时必须大于 0")
        if self.read_timeout_seconds <= 0:
            raise ValueError("读取超时必须大于 0")
