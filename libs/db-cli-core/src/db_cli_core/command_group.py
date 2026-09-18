"""Catch Click's parser errors before it prints unstructured usage text."""

import sys
from collections.abc import Sequence
from contextlib import suppress
from typing import Any

import click

from db_cli_core.context import CommandContext
from db_cli_core.enums import OutputMode
from db_cli_core.errors import CliError
from db_cli_core.output import emit_result
from mcp_base.types import ToolStatus


class AgentGroup(click.Group):
    def main(
        self,
        args: Sequence[str] | None = None,
        prog_name: str | None = None,
        complete_var: str | None = None,
        standalone_mode: bool = True,
        **kwargs: Any,
    ) -> Any:
        arguments = list(sys.argv[1:] if args is None else args)
        standalone = standalone_mode
        try:
            result = super().main(
                args=arguments, prog_name=prog_name, complete_var=complete_var, standalone_mode=False, **kwargs
            )
        except click.ClickException as exc:
            click_context = getattr(exc, "ctx", None)
            context = click_context.find_object(CommandContext) if click_context else kwargs.get("obj")
            use_json = "--json" in arguments or (context and context.output_mode is OutputMode.JSON)
            if not use_json:
                if not standalone:
                    raise
                exc.show()
            else:
                failure = CliError(status=ToolStatus.ERROR, message=exc.format_message(), code="INVALID_ARGUMENT")
                with suppress(click.exceptions.Exit):
                    emit_result(failure, OutputMode.JSON, context.profile_name if context else None)
            result = exc.exit_code
        if standalone:
            raise SystemExit(result if isinstance(result, int) else 0)
        return result
