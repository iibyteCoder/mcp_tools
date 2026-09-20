"""Small Redis client boundary used by the CLI application."""

from __future__ import annotations

from contextlib import suppress
from typing import TYPE_CHECKING, NamedTuple, Protocol, cast

from redis import Redis
from redis.exceptions import AuthenticationError, ResponseError
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from redis_cli.enums import ErrorCode

if TYPE_CHECKING:
    from collections.abc import Sequence

    from redis_cli.domain import RedisConnectionConfig


class RedisOperationError(RuntimeError):
    """A Redis operation failed with a stable CLI-facing category."""

    def __init__(self, code: ErrorCode, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


class RedisScanResult(NamedTuple):
    """Typed result returned by Redis scan commands."""

    cursor: int
    values: Sequence[object]


class RedisHashScanResult(NamedTuple):
    """Typed result returned by Redis hash/set scan commands."""

    cursor: int
    values: dict[object, object]


class RedisSetScanResult(NamedTuple):
    """Typed result returned by Redis set scan commands."""

    cursor: int
    values: Sequence[object]


class RedisScoredMember(NamedTuple):
    """One sorted-set member and its score."""

    member: object
    score: object


class RedisPipeline(Protocol):
    """Small typed subset of redis-py's pipeline API used by the CLI."""

    def execute_command(self, command: str, *arguments: object) -> RedisPipeline: ...

    def execute(self) -> object: ...


class RedisClient(Protocol):
    """Small typed subset of redis-py's synchronous client API."""

    def ping(self) -> object: ...

    def info(self, section: str) -> object: ...

    def dbsize(self) -> object: ...

    def flushdb(self) -> object: ...

    def pipeline(self, transaction: bool = True) -> RedisPipeline: ...

    def scan(self, cursor: int = 0, match: str | None = None, count: int | None = None) -> RedisScanResult: ...

    def type(self, name: str) -> object: ...

    def ttl(self, name: str) -> object: ...

    def get(self, name: str) -> object: ...

    def strlen(self, name: str) -> object: ...

    def hscan(self, name: str, count: int | None = None) -> RedisHashScanResult: ...

    def hlen(self, name: str) -> object: ...

    def lrange(self, name: str, start: int, end: int) -> Sequence[object]: ...

    def llen(self, name: str) -> object: ...

    def sscan(self, name: str, count: int | None = None) -> RedisSetScanResult: ...

    def scard(self, name: str) -> object: ...

    def zrange(self, name: str, start: int, end: int, withscores: bool = False) -> Sequence[RedisScoredMember]: ...

    def zcard(self, name: str) -> object: ...

    def execute_command(self, command: str, *arguments: object) -> object: ...

    def close(self) -> object: ...


class RedisClientFactory:
    """Create one short-lived redis-py client per CLI invocation."""

    def create(self, config: RedisConnectionConfig) -> RedisClient:
        try:
            client = Redis.from_url(
                config.url,
                socket_connect_timeout=config.settings.connection_timeout,
                socket_timeout=config.settings.connection_timeout,
                decode_responses=False,
            )
            return cast("RedisClient", client)
        except (ValueError, TypeError) as exc:
            raise RedisOperationError(ErrorCode.INVALID_ARGUMENT, "Redis connection settings are invalid") from exc


def translate_redis_error(error: Exception) -> RedisOperationError:
    """Translate redis-py exceptions without exposing credentials."""

    if isinstance(error, AuthenticationError):
        return RedisOperationError(ErrorCode.AUTH_FAILED, "Redis authentication failed")
    if isinstance(error, RedisTimeoutError):
        return RedisOperationError(ErrorCode.TIMEOUT, "Redis operation timed out", retryable=True)
    if isinstance(error, RedisConnectionError):
        return RedisOperationError(ErrorCode.CONNECTION_FAILED, "Redis connection failed", retryable=True)
    if isinstance(error, ResponseError):
        return RedisOperationError(ErrorCode.EXECUTION_FAILED, str(error))
    return RedisOperationError(ErrorCode.EXECUTION_FAILED, "Redis operation failed")


def close_client(client: RedisClient) -> None:
    """Close sync and async-compatible test doubles safely."""

    close = getattr(client, "close", None)
    if close is not None:
        with suppress(Exception):
            close()


__all__ = [
    "RedisClient",
    "RedisClientFactory",
    "RedisHashScanResult",
    "RedisOperationError",
    "RedisPipeline",
    "RedisScanResult",
    "RedisScoredMember",
    "RedisSetScanResult",
    "close_client",
    "translate_redis_error",
]
