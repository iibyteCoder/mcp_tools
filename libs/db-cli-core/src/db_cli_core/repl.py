"""Prompt-toolkit REPL that reuses the exact one-shot Click command tree."""

from __future__ import annotations

import shlex
from typing import TYPE_CHECKING

import click
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory

from db_cli_core.enums import ReplCommand

if TYPE_CHECKING:
    from db_cli_core.context import CommandContext


def run_repl(root: click.Group, context: CommandContext, application_name: str, history_path: str) -> None:
    click.echo(f"{application_name} interactive mode. 输入 help 查看命令, exit 退出。")
    session: PromptSession[str] = PromptSession(history=FileHistory(history_path))
    while True:
        try:
            line = session.prompt(f"{application_name}[{context.backend.target_label}]> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            continue
        if line in {ReplCommand.EXIT.value, ReplCommand.QUIT.value}:
            break
        if line == ReplCommand.HELP.value:
            click.echo(root.get_help(click.Context(root)))
            continue
        try:
            root.main(args=shlex.split(line), obj=context, standalone_mode=False)
        except click.ClickException as exc:
            click.echo(f"错误: {exc.format_message()}", err=True)
        except click.exceptions.Exit:
            continue
