"""Shared Click runtime, validation types and command helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

import click

from db_cli_kit.profiles import ProfileName
from db_cli_kit.secrets import KeyringSecretStore
from redis_cli.adapters.redis_py import RedisPyClientFactory
from redis_cli.application import OperationResult, RedisApplication
from redis_cli.command_meta import CommandMeta
from redis_cli.constants import PASSWORD_SERVICE_NAME
from redis_cli.domain.errors import RedisCliError
from redis_cli.domain.profiles import ConnectionOverrides
from redis_cli.enums import CommandGroup, ErrorCode, RedisCommand
from redis_cli.rendering import emit_failure, emit_success
from redis_cli.service import ProfileService
from redis_cli.store import JsonProfileStore

if TYPE_CHECKING:
    from collections.abc import Sequence

    from redis_cli.domain.profiles import ProfileRecord
    from redis_cli.json_types import ProfileView
    from redis_cli.ports.redis_client import RedisClientFactory


class ProfileNameType(click.ParamType):
    """Click converter for validated profile names."""

    name = "profile"

    def convert(self, value: object, param: click.Parameter | None, ctx: click.Context | None) -> ProfileName:
        if isinstance(value, ProfileName):
            return value
        try:
            return ProfileName(value=str(value))
        except ValueError as exc:
            self.fail(str(exc), param, ctx)
            raise AssertionError("Click ParamType.fail always raises") from exc


PROFILE_NAME = ProfileNameType()
PATH = click.Path(path_type=Path, dir_okay=True, file_okay=False)
POSITIVE_FLOAT = click.FloatRange(min=0.000001)
NONNEGATIVE_INT = click.IntRange(min=0)
PORT = click.IntRange(min=1, max=65_535)


class ActionOperation(Protocol):
    """Bound application operation that resolves its own connection."""

    def __call__(
        self,
        profile: ProfileName | None,
        overrides: ConnectionOverrides,
    ) -> OperationResult: ...


@dataclass(slots=True)
class CliRuntime:
    """Dependencies, root options and active command metadata for one invocation."""

    profile_service: ProfileService
    application: RedisApplication
    selected_profile: ProfileName | None = None
    overrides: ConnectionOverrides = field(default_factory=ConnectionOverrides)
    meta: CommandMeta = field(default_factory=CommandMeta)

    def begin(self, group: CommandGroup, action: str, profile: ProfileName | None = None) -> None:
        """Record the command that is about to execute."""

        self.meta = CommandMeta(group=group, action=action, profile=profile)

    def success_meta(self, profile: ProfileName | None) -> CommandMeta:
        """Return the metadata for a successful envelope."""

        return CommandMeta(group=self.meta.group, action=self.meta.action, profile=profile)

    def failure_meta(self) -> CommandMeta:
        """Return the metadata for a failed envelope."""

        profile = self.meta.profile if self.meta.profile is not None else self.selected_profile
        return CommandMeta(group=self.meta.group, action=self.meta.action, profile=profile)


def create_runtime(
    *,
    store_path: Path | None = None,
    working_directory: Path | None = None,
    client_factory: RedisClientFactory | None = None,
) -> CliRuntime:
    """Build the production dependency graph without opening Redis."""

    profile_service = ProfileService(
        JsonProfileStore(path=store_path, lock_timeout=JsonProfileStore.LOCK_TIMEOUT_SECONDS),
        KeyringSecretStore(PASSWORD_SERVICE_NAME),
        working_directory=working_directory,
    )
    application = RedisApplication(profile_service, client_factory or RedisPyClientFactory())
    return CliRuntime(profile_service=profile_service, application=application)


class JsonClickGroup(click.Group):
    """Translate expected failures into JSON while keeping help text plain."""

    def main(  # type: ignore[override]
        self,
        args: Sequence[str] | None = None,
        prog_name: str | None = None,
        complete_var: str | None = None,
        standalone_mode: bool = True,
        **extra: object,
    ) -> int | None:
        current = extra.get("obj")
        runtime = current if isinstance(current, CliRuntime) else create_runtime()
        extra["obj"] = runtime
        try:
            result = super().main(
                args=args,
                prog_name=prog_name,
                complete_var=complete_var,
                standalone_mode=False,
                **extra,
            )
            exit_code = 0 if result is None else int(result)
        except click.exceptions.Exit as control:
            exit_code = int(control.exit_code)
        except RedisCliError as error:
            exit_code = emit_failure(error, runtime.failure_meta())
        except click.Abort:
            exit_code = emit_failure(
                RedisCliError(ErrorCode.CANCELLED, "operation cancelled"),
                runtime.failure_meta(),
            )
        except click.ClickException as error:
            exit_code = emit_failure(
                RedisCliError(ErrorCode.INVALID_ARGUMENT, error.format_message()),
                runtime.failure_meta(),
            )
        except Exception:
            exit_code = emit_failure(
                RedisCliError(ErrorCode.INTERNAL_ERROR, "internal error"),
                runtime.failure_meta(),
            )
        if standalone_mode and exit_code != 0:
            raise SystemExit(exit_code)
        return exit_code


def runtime(ctx: click.Context) -> CliRuntime:
    """Return the typed invocation runtime from a Click context."""

    value = ctx.ensure_object(CliRuntime)
    if not isinstance(value, CliRuntime):
        raise TypeError("Click context object must be CliRuntime")
    return value


def start_command(
    ctx: click.Context,
    group: CommandGroup,
    action: str,
    *,
    profile: ProfileName | None = None,
) -> CliRuntime:
    """Record the active command and return the invocation runtime."""

    current = runtime(ctx)
    current.begin(group, action, profile)
    return current


def emit_result(current: CliRuntime, result: OperationResult) -> None:
    """Render one application result with its resolved profile."""

    emit_success(result.data, current.success_meta(result.profile))


def run_action(
    ctx: click.Context,
    operation: ActionOperation,
    *,
    group: CommandGroup,
    action: str,
) -> None:
    """Execute one bound application operation for a known command group."""

    current = start_command(ctx, group, action)
    emit_result(current, operation(current.selected_profile, current.overrides))


_COMMAND_GROUPS: dict[RedisCommand, CommandGroup] = {
    RedisCommand.APPEND: CommandGroup.STRING,
    RedisCommand.DEL: CommandGroup.KEY,
    RedisCommand.EXISTS: CommandGroup.KEY,
    RedisCommand.EXPIRE: CommandGroup.KEY,
    RedisCommand.GET: CommandGroup.STRING,
    RedisCommand.HDEL: CommandGroup.HASH,
    RedisCommand.HGET: CommandGroup.HASH,
    RedisCommand.HGETALL: CommandGroup.HASH,
    RedisCommand.HEXISTS: CommandGroup.HASH,
    RedisCommand.HKEYS: CommandGroup.HASH,
    RedisCommand.HLEN: CommandGroup.HASH,
    RedisCommand.HSET: CommandGroup.HASH,
    RedisCommand.HVALS: CommandGroup.HASH,
    RedisCommand.INCRBY: CommandGroup.STRING,
    RedisCommand.LINDEX: CommandGroup.LIST,
    RedisCommand.LLEN: CommandGroup.LIST,
    RedisCommand.LPOP: CommandGroup.LIST,
    RedisCommand.LPUSH: CommandGroup.LIST,
    RedisCommand.LRANGE: CommandGroup.LIST,
    RedisCommand.LTRIM: CommandGroup.LIST,
    RedisCommand.MGET: CommandGroup.STRING,
    RedisCommand.MSET: CommandGroup.STRING,
    RedisCommand.PERSIST: CommandGroup.KEY,
    RedisCommand.RANDOMKEY: CommandGroup.KEY,
    RedisCommand.RENAME: CommandGroup.KEY,
    RedisCommand.RPOP: CommandGroup.LIST,
    RedisCommand.RPUSH: CommandGroup.LIST,
    RedisCommand.SADD: CommandGroup.SET,
    RedisCommand.SCARD: CommandGroup.SET,
    RedisCommand.SISMEMBER: CommandGroup.SET,
    RedisCommand.SMEMBERS: CommandGroup.SET,
    RedisCommand.SREM: CommandGroup.SET,
    RedisCommand.SET: CommandGroup.STRING,
    RedisCommand.STRLEN: CommandGroup.STRING,
    RedisCommand.TTL: CommandGroup.KEY,
    RedisCommand.TYPE: CommandGroup.KEY,
    RedisCommand.ZADD: CommandGroup.ZSET,
    RedisCommand.ZCARD: CommandGroup.ZSET,
    RedisCommand.ZRANGE: CommandGroup.ZSET,
    RedisCommand.ZRANK: CommandGroup.ZSET,
    RedisCommand.ZREM: CommandGroup.ZSET,
    RedisCommand.ZREVRANGE: CommandGroup.ZSET,
    RedisCommand.ZREVRANK: CommandGroup.ZSET,
    RedisCommand.ZSCORE: CommandGroup.ZSET,
}


def command_group(command: RedisCommand) -> CommandGroup:
    """Return the top-level command group that owns one Redis command."""

    return _COMMAND_GROUPS[command]


def run_command(ctx: click.Context, command: RedisCommand, arguments: tuple[str, ...]) -> None:
    """Execute one raw Redis command through the application boundary."""

    current = start_command(ctx, command_group(command), command.value.lower())
    emit_result(
        current,
        current.application.command(current.selected_profile, current.overrides, command, arguments),
    )


def profile_data(profile: ProfileRecord) -> ProfileView:
    """Build the secret-free JSON view of a saved profile."""

    return {
        "name": profile.name.value,
        "host": profile.settings.host,
        "port": profile.settings.port,
        "username": profile.settings.username,
        "database": profile.settings.database,
        "connection_timeout": profile.settings.connection_timeout,
        "tls": profile.settings.tls,
        "description": profile.description,
        "password_present": profile.password_present,
    }


__all__ = [
    "NONNEGATIVE_INT",
    "PATH",
    "PORT",
    "POSITIVE_FLOAT",
    "PROFILE_NAME",
    "CliRuntime",
    "JsonClickGroup",
    "command_group",
    "create_runtime",
    "emit_result",
    "profile_data",
    "run_action",
    "run_command",
    "runtime",
    "start_command",
]
