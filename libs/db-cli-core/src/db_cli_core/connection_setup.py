"""Shared precedence and lifecycle setup for database composition roots."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from db_cli_core.enums import OutputMode
from db_cli_core.errors import error_result
from db_cli_core.output import emit_result

if TYPE_CHECKING:
    from db_cli_core.context import CommandContext
    from db_cli_core.profiles import ConnectionProfileManager


def configure_command_context(
    context: CommandContext,
    manager: ConnectionProfileManager,
    profile_name: str | None,
    explicit_settings: dict[str, Any],
    use_json: bool,
) -> None:
    context.profile_manager = manager
    context.output_mode = OutputMode.JSON if use_json else OutputMode.HUMAN
    try:
        if profile_name is not None or not context.connection_initialized:
            context.activate(manager.resolve(profile_name=profile_name))
        context.backend.configure(**explicit_settings)
        if any(value is not None for value in explicit_settings.values()):
            context.mark_explicit()
    except Exception as exc:
        emit_result(error_result(exc), context.output_mode, context.profile_name)
