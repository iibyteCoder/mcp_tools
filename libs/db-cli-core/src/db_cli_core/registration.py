"""Register a command catalog on a Click root group."""

from __future__ import annotations

from collections import OrderedDict
from typing import TYPE_CHECKING, Any

import click

from db_cli_core.context import CommandContext
from db_cli_core.execution import execute_safely
from db_cli_core.file_input import resolve_file_input
from db_cli_core.output import emit_result
from db_cli_core.schema_options import build_options, normalize_arguments

if TYPE_CHECKING:
    from db_cli_core.catalog import CommandCatalog


def register_catalog(root: click.Group, catalog: CommandCatalog) -> None:
    groups: OrderedDict[str, click.Group] = OrderedDict()
    for descriptor in catalog:
        group = groups.get(descriptor.group_name)
        if group is None:
            group = click.Group(descriptor.group_name, help=descriptor.group_help)
            groups[descriptor.group_name] = group
            root.add_command(group)

        def invoke_command(
            _tool_name: str = descriptor.tool_name,
            _input_field: str | None = {
                "mysql_query": "query",
                "mysql_execute": "query",
                "redis_pipeline": "commands",
            }.get(descriptor.tool_name),
            **arguments: Any,
        ) -> None:
            context = click.get_current_context().find_object(CommandContext)
            if context is None:
                raise click.ClickException("CLI 上下文未初始化")
            if _input_field:
                resolve_file_input(arguments, _input_field)
            result = execute_safely(lambda: context.backend.invoke(_tool_name, normalize_arguments(arguments)))
            emit_result(result, context.output_mode, context.profile_name)

        parameters: list[click.Parameter] = list(build_options(descriptor.input_schema))
        input_field = {"mysql_query": "query", "mysql_execute": "query", "redis_pipeline": "commands"}.get(
            descriptor.tool_name
        )
        if input_field:
            for parameter in parameters:
                if parameter.name == input_field:
                    parameter.required = False
            parameters.append(click.Option([f"--{input_field}-file"], help="读取 UTF-8 文件, - 表示 stdin"))
        group.add_command(
            click.Command(
                descriptor.command_name,
                params=parameters,
                callback=invoke_command,
                help=descriptor.description,
            )
        )
