"""redis-py adapter that implements the typed Redis client port."""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import contextmanager, suppress
from typing import TYPE_CHECKING, Protocol, cast

from redis import Redis
from redis.exceptions import AuthenticationError, ResponseError
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from redis_cli.domain.errors import RedisCliError, operation_failed_error
from redis_cli.enums import ErrorCode
from redis_cli.ports.redis_client import (
    RedisHashPage,
    RedisScanPage,
    RedisScoredMember,
    RedisSetPage,
)
from redis_cli.values import key_type, to_integer, to_json_value, to_number, to_text

if TYPE_CHECKING:
    from collections.abc import Iterator

    from redis.client import Pipeline

    from db_cli_kit.json_codec import JsonValue
    from redis_cli.domain.profiles import RedisConnectionConfig
    from redis_cli.enums import RedisKeyType
    from redis_cli.ports.redis_client import RedisClient, RedisPipeline


class _CommandExecutor(Protocol):
    """Typed subset of redis-py's untyped raw command surface."""

    def execute_command(self, *args: object) -> object: ...


class _PipelineCommands(Protocol):
    """Typed subset of redis-py's untyped pipeline command surface."""

    def execute_command(self, *args: object) -> object: ...

    def execute(self) -> object: ...


class RedisPyClient:
    """Adapt one redis-py synchronous client to the typed Redis client port."""

    def __init__(self, client: Redis) -> None:
        self._client = client

    def ping(self) -> bool:
        with _translated_errors():
            return bool(self._client.ping())

    def info(self, section: str) -> JsonValue:
        with _translated_errors():
            return to_json_value(self._client.info(section))

    def dbsize(self) -> int:
        with _translated_errors():
            return to_integer(self._client.dbsize())

    def flushdb(self) -> bool:
        with _translated_errors():
            return bool(self._client.flushdb())

    def pipeline(self, transaction: bool = True) -> RedisPipeline:
        return RedisPyPipeline(self._client.pipeline(transaction=transaction))

    def scan(self, cursor: int = 0, match: str | None = None, count: int | None = None) -> RedisScanPage:
        with _translated_errors():
            raw = self._client.scan(cursor=cursor, match=match, count=count)
            next_cursor, payload = _scan_pair(raw)
            return RedisScanPage(cursor=to_integer(next_cursor), keys=_text_items(payload))

    def type(self, name: str) -> RedisKeyType:
        with _translated_errors():
            return key_type(self._client.type(name))

    def ttl(self, name: str) -> int:
        with _translated_errors():
            return to_integer(self._client.ttl(name))

    def strlen(self, name: str) -> int:
        with _translated_errors():
            return to_integer(self._client.strlen(name))

    def hlen(self, name: str) -> int:
        with _translated_errors():
            return to_integer(self._client.hlen(name))

    def llen(self, name: str) -> int:
        with _translated_errors():
            return to_integer(self._client.llen(name))

    def scard(self, name: str) -> int:
        with _translated_errors():
            return to_integer(self._client.scard(name))

    def zcard(self, name: str) -> int:
        with _translated_errors():
            return to_integer(self._client.zcard(name))

    def get(self, name: str) -> str | None:
        with _translated_errors():
            value = self._client.get(name)
            return None if value is None else to_text(value)

    def hscan(self, name: str, count: int | None = None) -> RedisHashPage:
        with _translated_errors():
            raw = self._client.hscan(name, count=count)
            next_cursor, payload = _scan_pair(raw)
            return RedisHashPage(cursor=to_integer(next_cursor), values=_hash_items(payload))

    def lrange(self, name: str, start: int, end: int) -> tuple[str, ...]:
        with _translated_errors():
            return _text_items(self._client.lrange(name, start, end))

    def sscan(self, name: str, count: int | None = None) -> RedisSetPage:
        with _translated_errors():
            raw = self._client.sscan(name, count=count)
            next_cursor, payload = _scan_pair(raw)
            return RedisSetPage(cursor=to_integer(next_cursor), values=_text_items(payload))

    def zrange(
        self,
        name: str,
        start: int,
        end: int,
        withscores: bool = False,
    ) -> tuple[RedisScoredMember, ...]:
        with _translated_errors():
            raw = self._client.zrange(name, start, end, withscores=withscores)
            return _scored_members(raw, withscores=withscores)

    def execute_command(self, command: str, *arguments: object) -> JsonValue:
        with _translated_errors():
            executor = cast("_CommandExecutor", self._client)
            return to_json_value(executor.execute_command(command, *arguments))

    def close(self) -> None:
        with suppress(Exception):
            self._client.close()


class RedisPyPipeline:
    """Adapt one redis-py pipeline to the typed pipeline port."""

    def __init__(self, pipeline: Pipeline) -> None:
        self._pipeline: _PipelineCommands = cast("_PipelineCommands", pipeline)

    def execute_command(self, command: str, *arguments: object) -> RedisPipeline:
        with _translated_errors():
            self._pipeline.execute_command(command, *arguments)
        return self

    def execute(self) -> JsonValue:
        with _translated_errors():
            return to_json_value(self._pipeline.execute())


class RedisPyClientFactory:
    """Create one short-lived redis-py client per CLI invocation."""

    def create(self, config: RedisConnectionConfig) -> RedisClient:
        try:
            client = Redis.from_url(
                config.url,
                socket_connect_timeout=config.settings.connection_timeout,
                socket_timeout=config.settings.connection_timeout,
                decode_responses=False,
            )
        except (ValueError, TypeError) as exc:
            raise RedisCliError(ErrorCode.INVALID_ARGUMENT, "Redis connection settings are invalid") from exc
        except Exception as exc:
            raise translate_redis_error(exc) from exc
        return RedisPyClient(client)


def translate_redis_error(error: Exception) -> RedisCliError:
    """Translate redis-py exceptions without exposing credentials."""

    if isinstance(error, AuthenticationError):
        return RedisCliError(ErrorCode.AUTH_FAILED, "Redis authentication failed")
    if isinstance(error, RedisTimeoutError):
        return RedisCliError(ErrorCode.TIMEOUT, "Redis operation timed out", retryable=True)
    if isinstance(error, RedisConnectionError):
        return RedisCliError(ErrorCode.CONNECTION_FAILED, "Redis connection failed", retryable=True)
    if isinstance(error, ResponseError):
        return RedisCliError(ErrorCode.EXECUTION_FAILED, str(error))
    return operation_failed_error()


@contextmanager
def _translated_errors() -> Iterator[None]:
    """Translate redis-py failures at the adapter boundary."""

    try:
        yield
    except RedisCliError:
        raise
    except Exception as exc:
        raise translate_redis_error(exc) from exc


def _scan_pair(raw: object) -> tuple[object, object]:
    """Split one redis-py SCAN-family response into cursor and payload."""

    if not isinstance(raw, tuple) or len(raw) != 2:
        raise TypeError("unexpected Redis scan response")
    cursor, payload = raw
    return cursor, payload


def _text_items(payload: object) -> tuple[str, ...]:
    """Convert one redis-py multi-bulk response into typed text."""

    if not isinstance(payload, (list, tuple)):
        raise TypeError("unexpected Redis multi-bulk response")
    return tuple(to_text(item) for item in payload)


def _hash_items(payload: object) -> dict[str, str]:
    """Convert one redis-py hash response into typed field/value pairs."""

    if not isinstance(payload, Mapping):
        raise TypeError("unexpected Redis hash response")
    return {to_text(field): to_text(value) for field, value in payload.items()}


def _scored_members(payload: object, *, withscores: bool) -> tuple[RedisScoredMember, ...]:
    """Convert one redis-py sorted-set response into typed members."""

    if not isinstance(payload, (list, tuple)):
        raise TypeError("unexpected Redis sorted-set response")
    if not withscores:
        return tuple(RedisScoredMember(member=to_text(item), score=None) for item in payload)
    members: list[RedisScoredMember] = []
    for item in payload:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise TypeError("unexpected Redis sorted-set score response")
        member, score = item
        members.append(RedisScoredMember(member=to_text(member), score=to_number(score)))
    return tuple(members)


__all__ = [
    "RedisPyClient",
    "RedisPyClientFactory",
    "RedisPyPipeline",
    "translate_redis_error",
]
