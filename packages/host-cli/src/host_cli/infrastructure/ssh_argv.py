"""Assembly of the ssh argument vector for one invocation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from host_cli.domain.enums import SshArgument, SshConfig, SshOption

if TYPE_CHECKING:
    from pathlib import Path

    from host_cli.domain.models import InvocationLimits, ProfileSettings

CONNECT_TIMEOUT_TEMPLATE: Final[str] = "ConnectTimeout={seconds:g}"
"""One attempt only, so a stale password cannot trip an account lockout."""


@dataclass(frozen=True, slots=True)
class SshPlan:
    """Everything needed to start one ssh process, ready for ``subprocess``."""

    argv: tuple[str, ...]
    target: str
    debug_log_path: Path


def build_argv(
    settings: ProfileSettings,
    limits: InvocationLimits,
    command: str,
    debug_log_path: Path,
    *,
    password_available: bool,
) -> tuple[str, ...]:
    """Build the ssh argv for one invocation.

    The command is a single argv element handed to the remote shell verbatim.
    Splitting it would silently rewrite the operator's quoting, and passing ssh
    several trailing arguments makes it join them with spaces, destroying both
    quotes and metacharacters.

    ``BatchMode=yes`` when no password exists disables every prompt, which is
    what makes an unauthenticated invocation fail fast instead of waiting.
    """

    options: list[str] = [option.value for option in SshOption]
    options.append(SshConfig.BATCH_MODE_DISABLED.value if password_available else SshConfig.BATCH_MODE_ENABLED.value)
    if password_available:
        options.append(SshConfig.ONE_PASSWORD_PROMPT.value)
    options.append(CONNECT_TIMEOUT_TEMPLATE.format(seconds=limits.connect_timeout))

    argv: list[str] = [
        SshArgument.CONFIG_FILE.value,
        SshConfig.NO_CONFIG_FILE.value,
        SshArgument.DEBUG_LOG.value,
        str(debug_log_path),
    ]
    for option in options:
        argv.extend((SshArgument.OPTION.value, option))
    argv.extend(
        (
            SshArgument.VERBOSE.value,
            SshArgument.PORT.value,
            str(settings.port),
            SshArgument.SEPARATOR.value,
            f"{settings.user}@{settings.host}",
            command,
        )
    )
    return tuple(argv)


def build_plan(
    settings: ProfileSettings,
    limits: InvocationLimits,
    command: str,
    debug_log_path: Path,
    *,
    password_available: bool,
) -> SshPlan:
    """Assemble the plan, keeping the target around for diagnostics."""

    return SshPlan(
        argv=build_argv(
            settings,
            limits,
            command,
            debug_log_path,
            password_available=password_available,
        ),
        target=f"{settings.user}@{settings.host}",
        debug_log_path=debug_log_path,
    )


__all__ = ["CONNECT_TIMEOUT_TEMPLATE", "SshPlan", "build_argv", "build_plan"]
