"""Shared Click runtime, validation types and command helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import click

from redis_cli.application import OperationResult, RedisAction, RedisApplication
from redis_cli.client import RedisClientFactory, RedisOperationError
from redis_cli.domain import ConnectionOverrides, ProfileName, ProfileNameError
from redis_cli.enums import ErrorCode, RedisCommand
from redis_cli.rendering import CliError, emit_failure, emit_success
from redis_cli.secrets import KeyringSecretStore
from redis_cli.service import ProfileService, ProfileServiceError
from redis_cli.store import JsonProfileStore, ProfileStoreError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from redis_cli.domain import ProfileRecord
    from redis_cli.json_types import ProfileView


class ProfileNameType(click.ParamType):
    """Click converter for validated profile names."""

    name = "profile"

    def convert(self, value: object, param: click.Parameter | None, ctx: click.Context | None) -> ProfileName:
        if isinstance(value, ProfileName):
            return value
        try:
            return ProfileName(str(value))
        except ProfileNameError as exc:
            self.fail(str(exc), param, ctx)
            raise AssertionError("Click ParamType.fail always raises") from exc


PROFILE_NAME = ProfileNameType()
PATH = click.Path(path_type=Path, dir_okay=True, file_okay=False)
POSITIVE_FLOAT = click.FloatRange(min=0.000001)
NONNEGATIVE_INT = click.IntRange(min=0)
PORT = click.IntRange(min=1, max=65_535)


@dataclass(slots=True)
class CliRuntime:
    """Dependencies and root options for one CLI invocation."""

    profile_service: ProfileService
    application: RedisApplication
    selected_profile: ProfileName | None = None
    overrides: ConnectionOverrides = field(default_factory=ConnectionOverrides)


def create_runtime(
    *,
    store_path: Path | None = None,
    working_directory: Path | None = None,
    client_factory: RedisClientFactory | None = None,
) -> CliRuntime:
    """Build the production dependency graph without opening Redis."""

    profile_service = ProfileService(
        JsonProfileStore(path=store_path, lock_timeout=JsonProfileStore.LOCK_TIMEOUT_SECONDS),
        KeyringSecretStore(),
        working_directory=working_directory,
    )
    application = RedisApplication(profile_service, client_factory or RedisClientFactory())
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
        except CliError as error:
            exit_code = emit_failure(profile_text(runtime.selected_profile), error)
        except ProfileStoreError as error:
            exit_code = emit_failure(
                profile_text(runtime.selected_profile),
                CliError(ErrorCode.PROFILE_REGISTRY, error.message, exit_code=4),
            )
        except ProfileServiceError as error:
            exit_code = emit_failure(
                profile_text(runtime.selected_profile),
                CliError(error.code, error.message, exit_code=_exit_code_for(error.code)),
            )
        except RedisOperationError as error:
            exit_code = emit_failure(
                profile_text(runtime.selected_profile),
                CliError(error.code, error.message, exit_code=5),
            )
        except click.Abort:
            exit_code = emit_failure(
                profile_text(runtime.selected_profile),
                CliError(ErrorCode.EXECUTION_FAILED, "operation cancelled", exit_code=5),
            )
        except click.ClickException as error:
            exit_code = emit_failure(
                profile_text(runtime.selected_profile),
                CliError(ErrorCode.INVALID_ARGUMENT, error.format_message(), exit_code=2),
            )
        except Exception:
            exit_code = emit_failure(
                profile_text(runtime.selected_profile),
                CliError(ErrorCode.INTERNAL_ERROR, "internal error", exit_code=70),
            )
        if standalone_mode and exit_code != 0:
            raise SystemExit(exit_code)
        return exit_code


def _exit_code_for(code: ErrorCode) -> int:
    return (
        2
        if code is ErrorCode.INVALID_ARGUMENT
        else 4
        if code
        in {
            ErrorCode.PROFILE_NOT_FOUND,
            ErrorCode.PROFILE_CONFLICT,
            ErrorCode.PROFILE_REGISTRY,
            ErrorCode.SECRET_STORE,
        }
        else 5
    )


def profile_text(profile: ProfileName | None) -> str | None:
    """Convert an optional domain profile name to its JSON representation."""

    return None if profile is None else profile.value


def runtime(ctx: click.Context) -> CliRuntime:
    """Return the typed invocation runtime from a Click context."""

    value = ctx.ensure_object(CliRuntime)
    if not isinstance(value, CliRuntime):
        raise TypeError("Click context object must be CliRuntime")
    return value


def emit_result(result: OperationResult) -> None:
    """Render one application result."""

    emit_success(profile_text(result.profile), result.data)


def run_action(ctx: click.Context, action: RedisAction) -> None:
    """Execute one typed application action."""

    current = runtime(ctx)
    emit_result(current.application.execute(current.selected_profile, current.overrides, action))


def run_command(ctx: click.Context, command: RedisCommand, arguments: tuple[str, ...]) -> None:
    """Execute one raw Redis command through the application boundary."""

    current = runtime(ctx)
    emit_result(current.application.command(current.selected_profile, current.overrides, command, arguments))


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
    "create_runtime",
    "emit_result",
    "profile_data",
    "profile_text",
    "run_action",
    "run_command",
    "runtime",
]
