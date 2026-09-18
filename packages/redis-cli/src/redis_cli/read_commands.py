"""CLI-only read helpers; the existing MCP command catalog stays unchanged."""

import click

from db_cli_core.context import CommandContext
from db_cli_core.execution import execute_safely
from db_cli_core.output import emit_result
from redis_cli.backend import RedisBackend


def register_read_commands(root: click.Group) -> None:
    group = root.commands["key"]
    assert isinstance(group, click.Group)

    def run(operation: str, **arguments: object) -> None:
        context = click.get_current_context().find_object(CommandContext)
        if context is None or not isinstance(context.backend, RedisBackend):
            raise click.ClickException("Redis CLI 上下文未初始化")
        backend = context.backend
        result = execute_safely(lambda: backend.read(operation, **arguments))
        emit_result(result, context.output_mode, context.profile_name)

    group.add_command(
        click.Command(
            "inspect",
            callback=lambda **args: run("inspect", **args),
            help="只读查看类型、TTL、长度及有限预览; 不是一致性快照",
            params=[
                click.Option(["--key"], required=True),
                click.Option(["--limit"], type=click.IntRange(1, 100), default=10, show_default=True),
                click.Option(["--max-bytes"], type=click.IntRange(1, 4096), default=256, show_default=True),
            ],
        )
    )
    group.add_command(
        click.Command(
            "scan",
            callback=lambda **args: run("scan", **args),
            help="按游标继续扫描, next_cursor=null 结束; 不是一致性快照",
            params=[
                click.Option(["--pattern"], default="*", show_default=True),
                click.Option(["--limit"], type=click.IntRange(1, 500), default=50, show_default=True),
                click.Option(["--cursor"], help="上次返回的本机游标, 24 小时有效"),
            ],
        )
    )
