"""Framework-neutral Redis operations and connection lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from redis_cli.client import (
    RedisClient,
    RedisClientFactory,
    RedisHashScanResult,
    RedisOperationError,
    RedisScanResult,
    RedisScoredMember,
    RedisSetScanResult,
    close_client,
    translate_redis_error,
)
from redis_cli.enums import RedisCommand, RedisKeyType
from redis_cli.json_types import FlushData, KeyInspectionData, KeyScanData, PingData
from redis_cli.values import (
    byte_preview,
    key_type,
    to_integer,
    to_json_value,
    to_number,
    to_text,
)

if TYPE_CHECKING:
    from redis_cli.domain import ConnectionOverrides, ProfileName
    from redis_cli.json_types import JsonOutput, JsonValue
    from redis_cli.service import ProfileService
    from redis_cli.values import PipelineRequest


class RedisAction(Protocol):
    """Callable seam for one Redis operation."""

    def __call__(self, client: RedisClient) -> JsonOutput: ...


@dataclass(frozen=True, slots=True)
class OperationResult:
    """One operation's profile metadata and JSON-safe data."""

    profile: ProfileName | None
    data: JsonOutput


@dataclass(frozen=True, slots=True)
class ValueInspection:
    """Structured preview of one Redis key's value."""

    length: int
    preview: JsonValue
    truncated: bool
    preview_supported: bool


class RedisApplication:
    """Run one short-lived Redis operation through the client boundary."""

    def __init__(self, profile_service: ProfileService, client_factory: RedisClientFactory) -> None:
        self.profile_service = profile_service
        self.client_factory = client_factory

    def execute(
        self,
        profile: ProfileName | None,
        overrides: ConnectionOverrides,
        action: RedisAction,
    ) -> OperationResult:
        resolved = self.profile_service.resolve(profile, overrides)
        client = self.client_factory.create(resolved.config)
        try:
            return OperationResult(profile=resolved.profile, data=action(client))
        except RedisOperationError:
            raise
        except Exception as exc:
            raise translate_redis_error(exc) from exc
        finally:
            close_client(client)

    def ping(self, profile: ProfileName | None, overrides: ConnectionOverrides) -> OperationResult:
        def run(client: RedisClient) -> PingData:
            return PingData(pong=bool(client.ping()))

        return self.execute(profile, overrides, run)

    def info(self, profile: ProfileName | None, overrides: ConnectionOverrides, section: str) -> OperationResult:
        def run(client: RedisClient) -> JsonValue:
            return to_json_value(client.info(section))

        return self.execute(profile, overrides, run)

    def dbsize(self, profile: ProfileName | None, overrides: ConnectionOverrides) -> OperationResult:
        def run(client: RedisClient) -> int:
            return to_integer(client.dbsize())

        return self.execute(profile, overrides, run)

    def flushdb(self, profile: ProfileName | None, overrides: ConnectionOverrides) -> OperationResult:
        def run(client: RedisClient) -> FlushData:
            return FlushData(flushed=bool(client.flushdb()))

        return self.execute(profile, overrides, run)

    def pipeline(
        self,
        profile: ProfileName | None,
        overrides: ConnectionOverrides,
        request: PipelineRequest,
    ) -> OperationResult:
        def run(client: RedisClient) -> JsonValue:
            pipeline = client.pipeline(transaction=False)
            for command in request.commands:
                pipeline.execute_command(command.name, *command.arguments)
            return to_json_value(pipeline.execute())

        return self.execute(profile, overrides, run)

    def scan(
        self,
        profile: ProfileName | None,
        overrides: ConnectionOverrides,
        *,
        pattern: str,
        cursor: int,
        limit: int,
    ) -> OperationResult:
        def run(client: RedisClient) -> KeyScanData:
            scan_result = RedisScanResult(*client.scan(cursor=cursor, match=pattern, count=limit))
            return KeyScanData(
                keys=[to_text(key) for key in scan_result.values],
                next_cursor=str(scan_result.cursor) if scan_result.cursor else None,
            )

        return self.execute(profile, overrides, run)

    def inspect_key(
        self,
        profile: ProfileName | None,
        overrides: ConnectionOverrides,
        *,
        key: str,
        max_bytes: int,
        limit: int,
    ) -> OperationResult:
        def run(client: RedisClient) -> KeyInspectionData:
            kind = key_type(client.type(key))
            ttl = to_integer(client.ttl(key))
            inspection = self._inspect_value(client, kind, key, max_bytes, limit)
            return KeyInspectionData(
                key=key,
                type=kind.value,
                ttl=ttl,
                length=inspection.length,
                preview_supported=inspection.preview_supported,
                preview=inspection.preview,
                truncated=inspection.truncated,
            )

        return self.execute(profile, overrides, run)

    @staticmethod
    def _inspect_value(
        client: RedisClient,
        kind: RedisKeyType,
        key: str,
        max_bytes: int,
        limit: int,
    ) -> ValueInspection:
        if kind is RedisKeyType.NONE:
            return ValueInspection(0, None, False, True)
        if kind is RedisKeyType.STRING:
            value = client.get(key)
            preview = byte_preview(value or b"", max_bytes)
            return ValueInspection(to_integer(client.strlen(key)), preview.text, preview.truncated, True)
        if kind is RedisKeyType.HASH:
            hash_scan = RedisHashScanResult(*client.hscan(key, count=limit))
            hash_values = hash_scan.values
            hash_preview = {to_text(field): to_text(value) for field, value in hash_values.items()}
            return ValueInspection(
                to_integer(client.hlen(key)),
                to_json_value(hash_preview),
                len(hash_values) < to_integer(client.hlen(key)),
                True,
            )
        if kind is RedisKeyType.LIST:
            list_values = client.lrange(key, 0, limit - 1)
            list_preview = [to_text(value) for value in list_values]
            list_length = to_integer(client.llen(key))
            return ValueInspection(list_length, to_json_value(list_preview), len(list_preview) < list_length, True)
        if kind is RedisKeyType.SET:
            set_scan = RedisSetScanResult(*client.sscan(key, count=limit))
            set_values = set_scan.values
            set_preview = [to_text(value) for value in set_values]
            set_length = to_integer(client.scard(key))
            return ValueInspection(set_length, to_json_value(set_preview), len(set_preview) < set_length, True)
        if kind is RedisKeyType.ZSET:
            zset_values = [RedisScoredMember(*value) for value in client.zrange(key, 0, limit - 1, withscores=True)]
            zset_preview = [[to_text(item.member), to_number(item.score)] for item in zset_values]
            zset_length = to_integer(client.zcard(key))
            return ValueInspection(zset_length, to_json_value(zset_preview), len(zset_preview) < zset_length, True)
        return ValueInspection(0, None, False, False)

    def command(
        self,
        profile: ProfileName | None,
        overrides: ConnectionOverrides,
        command: RedisCommand,
        arguments: tuple[str, ...],
    ) -> OperationResult:
        def run(client: RedisClient) -> JsonValue:
            return to_json_value(client.execute_command(command.value, *arguments))

        return self.execute(profile, overrides, run)


__all__ = ["OperationResult", "RedisAction", "RedisApplication", "ValueInspection"]
