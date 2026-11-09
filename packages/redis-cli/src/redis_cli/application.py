"""Framework-neutral Redis operations and connection lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, cast

from redis_cli.domain.errors import RedisCliError, operation_failed_error
from redis_cli.enums import RedisCommand, RedisKeyType
from redis_cli.json_types import FlushData, KeyInspectionData, KeyScanData, PingData
from redis_cli.values import byte_preview, to_json_value

if TYPE_CHECKING:
    from db_cli_kit.json_codec import JsonValue
    from db_cli_kit.profiles import ProfileName
    from redis_cli.domain.profiles import ConnectionOverrides
    from redis_cli.json_types import JsonOutput
    from redis_cli.ports.redis_client import RedisClient, RedisClientFactory
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
        except RedisCliError:
            raise
        except Exception as exc:
            raise operation_failed_error() from exc
        finally:
            client.close()

    def ping(self, profile: ProfileName | None, overrides: ConnectionOverrides) -> OperationResult:
        def run(client: RedisClient) -> JsonValue:
            return cast("JsonValue", PingData(pong=client.ping()))

        return self.execute(profile, overrides, run)

    def info(self, profile: ProfileName | None, overrides: ConnectionOverrides, section: str) -> OperationResult:
        def run(client: RedisClient) -> JsonValue:
            return client.info(section)

        return self.execute(profile, overrides, run)

    def dbsize(self, profile: ProfileName | None, overrides: ConnectionOverrides) -> OperationResult:
        def run(client: RedisClient) -> int:
            return client.dbsize()

        return self.execute(profile, overrides, run)

    def flushdb(self, profile: ProfileName | None, overrides: ConnectionOverrides) -> OperationResult:
        def run(client: RedisClient) -> JsonValue:
            return cast("JsonValue", FlushData(flushed=client.flushdb()))

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
            return pipeline.execute()

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
        def run(client: RedisClient) -> JsonValue:
            page = client.scan(cursor=cursor, match=pattern, count=limit)
            return cast(
                "JsonValue",
                KeyScanData(
                    keys=list(page.keys),
                    next_cursor=str(page.cursor) if page.cursor else None,
                ),
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
        def run(client: RedisClient) -> JsonValue:
            kind = client.type(key)
            ttl = client.ttl(key)
            inspection = self._inspect_value(client, kind, key, max_bytes, limit)
            return cast(
                "JsonValue",
                KeyInspectionData(
                    key=key,
                    type=kind.value,
                    ttl=ttl,
                    length=inspection.length,
                    preview_supported=inspection.preview_supported,
                    preview=inspection.preview,
                    truncated=inspection.truncated,
                ),
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
            preview = byte_preview(client.get(key) or "", max_bytes)
            return ValueInspection(client.strlen(key), preview.text, preview.truncated, True)
        if kind is RedisKeyType.HASH:
            hash_values = client.hscan(key, count=limit).values
            hash_length = client.hlen(key)
            return ValueInspection(
                hash_length,
                to_json_value(hash_values),
                len(hash_values) < hash_length,
                True,
            )
        if kind is RedisKeyType.LIST:
            list_values = client.lrange(key, 0, limit - 1)
            list_length = client.llen(key)
            return ValueInspection(
                list_length,
                to_json_value(list_values),
                len(list_values) < list_length,
                True,
            )
        if kind is RedisKeyType.SET:
            set_values = client.sscan(key, count=limit).values
            set_length = client.scard(key)
            return ValueInspection(
                set_length,
                to_json_value(set_values),
                len(set_values) < set_length,
                True,
            )
        if kind is RedisKeyType.ZSET:
            zset_values = client.zrange(key, 0, limit - 1, withscores=True)
            zset_preview = [[item.member, item.score] for item in zset_values]
            zset_length = client.zcard(key)
            return ValueInspection(
                zset_length,
                to_json_value(zset_preview),
                len(zset_preview) < zset_length,
                True,
            )
        return ValueInspection(0, None, False, False)

    def command(
        self,
        profile: ProfileName | None,
        overrides: ConnectionOverrides,
        command: RedisCommand,
        arguments: tuple[str, ...],
    ) -> OperationResult:
        def run(client: RedisClient) -> JsonValue:
            return client.execute_command(command.value, *arguments)

        return self.execute(profile, overrides, run)


__all__ = ["OperationResult", "RedisAction", "RedisApplication", "ValueInspection"]
