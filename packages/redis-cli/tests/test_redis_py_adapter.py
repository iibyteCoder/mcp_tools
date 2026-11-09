"""Typed conversion and error translation in the redis-py adapter."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest
from redis.exceptions import AuthenticationError, ResponseError
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from redis_cli.adapters.redis_py import RedisPyClient, RedisPyClientFactory, translate_redis_error
from redis_cli.domain.errors import RedisCliError
from redis_cli.domain.profiles import RedisConnectionConfig, RedisSettings
from redis_cli.domain.secrets import SecretValue
from redis_cli.enums import ErrorCode, RedisKeyType
from redis_cli.ports.redis_client import RedisHashPage, RedisScanPage, RedisScoredMember, RedisSetPage

if TYPE_CHECKING:
    from redis import Redis


class RawPipeline:
    """Redis-py-shaped pipeline double returning raw wire values."""

    def __init__(self) -> None:
        self.commands: list[tuple[str, tuple[object, ...]]] = []

    def execute_command(self, command: str, *arguments: object) -> RawPipeline:
        self.commands.append((command, arguments))
        return self

    def execute(self) -> list[object]:
        return [b"OK", 1]


class RawRedis:
    """Redis-py-shaped client double returning raw wire values."""

    def __init__(self) -> None:
        self.transactions: list[bool] = []
        self.raw_pipeline = RawPipeline()
        self.closed = False
        self.info_section = ""

    def ping(self) -> bool:
        return True

    def info(self, section: str) -> dict[bytes, object]:
        self.info_section = section
        return {b"redis_version": b"7.2.0", b"connected_clients": 1}

    def dbsize(self) -> bytes:
        return b"12"

    def flushdb(self) -> bool:
        return True

    def pipeline(self, transaction: bool = True) -> RawPipeline:
        self.transactions.append(transaction)
        return self.raw_pipeline

    def scan(self, cursor: int = 0, match: str | None = None, count: int | None = None) -> tuple[int, list[bytes]]:
        return 7, [b"alpha", b"beta"]

    def type(self, name: str) -> bytes:
        return b"hash"

    def ttl(self, name: str) -> int:
        return 42

    def strlen(self, name: str) -> bytes:
        return b"5"

    def hlen(self, name: str) -> int:
        return 2

    def llen(self, name: str) -> int:
        return 2

    def scard(self, name: str) -> int:
        return 1

    def zcard(self, name: str) -> int:
        return 1

    def get(self, name: str) -> bytes | None:
        return None if name == "missing" else b"value"

    def hscan(self, name: str, count: int | None = None) -> tuple[int, dict[bytes, bytes]]:
        return 0, {b"field": b"value"}

    def lrange(self, name: str, start: int, end: int) -> list[bytes]:
        return [b"first", b"second"]

    def sscan(self, name: str, count: int | None = None) -> tuple[int, list[bytes]]:
        return 0, [b"member"]

    def zrange(self, name: str, start: int, end: int, withscores: bool = False) -> list[object]:
        return [[b"Ada", b"10.5"]] if withscores else [b"Ada"]

    def execute_command(self, command: str, *arguments: object) -> object:
        return b"OK" if command == "SET" else [b"a", 1]

    def close(self) -> None:
        self.closed = True


def adapt(raw: RawRedis) -> RedisPyClient:
    """Wrap one raw client double in the adapter under test."""

    return RedisPyClient(cast("Redis", raw))


def test_scalar_responses_are_converted_to_the_typed_port() -> None:
    client = adapt(RawRedis())

    assert client.ping() is True
    assert client.dbsize() == 12
    assert client.flushdb() is True
    assert client.get("present") == "value"
    assert client.get("missing") is None
    assert client.type("any") is RedisKeyType.HASH
    assert client.ttl("any") == 42
    assert client.strlen("any") == 5
    assert client.hlen("any") == 2
    assert client.llen("any") == 2
    assert client.scard("any") == 1
    assert client.zcard("any") == 1


def test_scan_family_responses_become_typed_pages() -> None:
    client = adapt(RawRedis())

    assert client.scan(cursor=0, match="*", count=10) == RedisScanPage(cursor=7, keys=("alpha", "beta"))
    assert client.hscan("hash", count=10) == RedisHashPage(cursor=0, values={"field": "value"})
    assert client.sscan("set", count=10) == RedisSetPage(cursor=0, values=("member",))
    assert client.lrange("list", 0, -1) == ("first", "second")


def test_sorted_set_responses_become_scored_members() -> None:
    client = adapt(RawRedis())

    assert client.zrange("scores", 0, -1, withscores=True) == (RedisScoredMember(member="Ada", score=10.5),)
    assert client.zrange("scores", 0, -1) == (RedisScoredMember(member="Ada", score=None),)


def test_info_and_raw_commands_become_kit_json_values() -> None:
    raw = RawRedis()
    client = adapt(raw)

    assert client.info("server") == {"redis_version": "7.2.0", "connected_clients": 1}
    assert raw.info_section == "server"
    assert client.execute_command("SET", "key", "value") == "OK"
    assert client.execute_command("MGET", "key") == ["a", 1]


def test_pipeline_forwards_commands_and_converts_results() -> None:
    raw = RawRedis()
    pipeline = adapt(raw).pipeline(transaction=False)

    assert pipeline.execute_command("SET", "key", "value") is pipeline
    assert pipeline.execute() == ["OK", 1]
    assert raw.transactions == [False]
    assert raw.raw_pipeline.commands == [("SET", ("key", "value"))]


def test_close_delegates_to_the_driver() -> None:
    raw = RawRedis()

    adapt(raw).close()

    assert raw.closed is True


@pytest.mark.parametrize(
    ("error", "code", "retryable"),
    [
        (AuthenticationError("denied"), ErrorCode.AUTH_FAILED, False),
        (RedisTimeoutError("slow"), ErrorCode.TIMEOUT, True),
        (RedisConnectionError("down"), ErrorCode.CONNECTION_FAILED, True),
        (ResponseError("WRONGTYPE wrong kind"), ErrorCode.EXECUTION_FAILED, False),
        (RuntimeError("boom"), ErrorCode.EXECUTION_FAILED, False),
    ],
)
def test_redis_errors_translate_to_stable_categories(
    error: Exception,
    code: ErrorCode,
    retryable: bool,
) -> None:
    translated = translate_redis_error(error)

    assert translated.code is code
    assert translated.retryable is retryable


def test_response_errors_keep_the_redis_message() -> None:
    translated = translate_redis_error(ResponseError("WRONGTYPE wrong kind"))

    assert translated.message == "WRONGTYPE wrong kind"
    assert str(translated) == "WRONGTYPE wrong kind"


class FailingRedis:
    """Redis double whose URL parsing always fails with a secret-bearing message."""

    @classmethod
    def from_url(cls, url: str, **kwargs: object) -> None:
        raise ValueError(f"invalid Redis URL: {url}")


def test_invalid_settings_error_does_not_reveal_the_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "s3cr3t-client-password"
    config = RedisConnectionConfig.from_settings(
        RedisSettings(host="127.0.0.1"),
        password=SecretValue(secret),
    )
    monkeypatch.setattr("redis_cli.adapters.redis_py.Redis", FailingRedis)

    with pytest.raises(RedisCliError) as failure:
        RedisPyClientFactory().create(config)

    assert failure.value.code is ErrorCode.INVALID_ARGUMENT
    assert secret not in failure.value.message
    assert secret not in str(failure.value)
