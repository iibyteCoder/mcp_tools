"""Typed Redis client boundary consumed by the application layer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Mapping

    from db_cli_kit.json_codec import JsonValue
    from redis_cli.domain.profiles import RedisConnectionConfig
    from redis_cli.enums import RedisKeyType


@dataclass(frozen=True, slots=True, kw_only=True)
class RedisScanPage:
    """One typed page of keys returned by SCAN."""

    cursor: int
    keys: tuple[str, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class RedisHashPage:
    """One typed page of field/value pairs returned by HSCAN."""

    cursor: int
    values: Mapping[str, str]


@dataclass(frozen=True, slots=True, kw_only=True)
class RedisSetPage:
    """One typed page of members returned by SSCAN."""

    cursor: int
    values: tuple[str, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class RedisScoredMember:
    """One sorted-set member and its score, when the command returned scores."""

    member: str
    score: float | None


class RedisPipeline(Protocol):
    """Small typed subset of the pipeline API consumed by the CLI."""

    def execute_command(self, command: str, *arguments: object) -> RedisPipeline: ...

    def execute(self) -> JsonValue: ...


class RedisClient(Protocol):
    """Small typed Redis client API consumed by the application layer."""

    def ping(self) -> bool: ...

    def info(self, section: str) -> JsonValue: ...

    def dbsize(self) -> int: ...

    def flushdb(self) -> bool: ...

    def pipeline(self, transaction: bool = True) -> RedisPipeline: ...

    def scan(self, cursor: int = 0, match: str | None = None, count: int | None = None) -> RedisScanPage: ...

    def type(self, name: str) -> RedisKeyType: ...

    def ttl(self, name: str) -> int: ...

    def strlen(self, name: str) -> int: ...

    def hlen(self, name: str) -> int: ...

    def llen(self, name: str) -> int: ...

    def scard(self, name: str) -> int: ...

    def zcard(self, name: str) -> int: ...

    def get(self, name: str) -> str | None: ...

    def hscan(self, name: str, count: int | None = None) -> RedisHashPage: ...

    def lrange(self, name: str, start: int, end: int) -> tuple[str, ...]: ...

    def sscan(self, name: str, count: int | None = None) -> RedisSetPage: ...

    def zrange(
        self,
        name: str,
        start: int,
        end: int,
        withscores: bool = False,
    ) -> tuple[RedisScoredMember, ...]: ...

    def execute_command(self, command: str, *arguments: object) -> JsonValue: ...

    def close(self) -> None: ...


class RedisClientFactory(Protocol):
    """Construct one short-lived Redis client per CLI invocation."""

    def create(self, config: RedisConnectionConfig) -> RedisClient: ...


__all__ = [
    "RedisClient",
    "RedisClientFactory",
    "RedisHashPage",
    "RedisPipeline",
    "RedisScanPage",
    "RedisScoredMember",
    "RedisSetPage",
]
