"""Static argparse command tree and typed request construction."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn

if TYPE_CHECKING:
    from collections.abc import Sequence

from mysql_command import __version__
from mysql_command.command_model import (
    ALL_ROUTES,
    SQL_ROUTES,
    CommandAction,
    CommandGroup,
    CommandRequest,
    DiagnosticErrorType,
    ErrorCode,
    ExitCode,
    SqlInputSpec,
)
from mysql_command.errors import CliFailure, ErrorDetail


class ParserExit(Exception):
    """Control flow used by argparse for help and version output."""

    __slots__ = ("status",)

    def __init__(self, status: int) -> None:
        super().__init__()
        self.status = status


class CliArgumentParser(argparse.ArgumentParser):
    """ArgumentParser that never writes parse errors to stderr."""

    def error(self, message: str) -> NoReturn:
        error_type = (
            DiagnosticErrorType.UNKNOWN_COMMAND
            if "invalid choice" in message
            else DiagnosticErrorType.ARGUMENT_SYNTAX
        )
        code = ErrorCode.UNKNOWN_COMMAND if error_type is DiagnosticErrorType.UNKNOWN_COMMAND else ErrorCode.INVALID_ARGUMENT
        raise CliFailure(
            code=code,
            message="未知命令" if error_type is DiagnosticErrorType.UNKNOWN_COMMAND else "命令参数无效",
            retryable=False,
            details=(ErrorDetail(error_type=error_type, argument=message),),
            exit_code=ExitCode.INVALID_ARGUMENT,
        )

    def exit(self, status: int = 0, message: str | None = None) -> NoReturn:
        del message
        raise ParserExit(status)


def build_parser() -> CliArgumentParser:
    """Build the static command tree without contacting any external service."""

    parser = CliArgumentParser(
        prog="db-mysql",
        description="JSON-only MySQL command line foundation.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="_route_group")
    help_parser = subparsers.add_parser("help", help="show command help")
    help_parser.set_defaults(_command_group=CommandGroup.HELP, _command_action=CommandAction.HELP)

    group_parsers: dict[CommandGroup, argparse.ArgumentParser] = {}
    action_parsers: dict[CommandGroup, argparse._SubParsersAction[argparse.ArgumentParser]] = {}
    for route in ALL_ROUTES:
        group_parser = group_parsers.get(route.group)
        if group_parser is None:
            group_parser = subparsers.add_parser(route.group.value, help=f"{route.group.value} commands")
            group_parsers[route.group] = group_parser
        action_subparsers = action_parsers.get(route.group)
        if action_subparsers is None:
            action_subparsers = group_parser.add_subparsers(dest="_route_action")
            action_parsers[route.group] = action_subparsers
        action_parser = action_subparsers.add_parser(route.action.value, help=f"{route.action.value} action")
        action_parser.set_defaults(_command_group=route.group, _command_action=route.action)
        if route in SQL_ROUTES:
            action_parser.add_argument("--sql", dest="_sql", help="inline SQL text")
            action_parser.add_argument("--sql-file", dest="_sql_file", type=Path, help="SQL file path; - reads stdin")
            action_parser.add_argument("--params-file", dest="_params_file", type=Path, help="JSON object or array")
    return parser


def parse_command_request(parser: argparse.ArgumentParser, argv: Sequence[str]) -> CommandRequest:
    """Parse argv into a typed request, applying input-source constraints."""

    namespace = parser.parse_args(list(argv))
    group = _required_group(namespace)
    action = _required_action(namespace)
    if group is CommandGroup.HELP:
        return CommandRequest(group=group, action=action)
    if group is CommandGroup.SQL:
        return _sql_request(namespace, group=group, action=action)
    return CommandRequest(group=group, action=action)


def _sql_request(
    namespace: argparse.Namespace,
    *,
    group: CommandGroup,
    action: CommandAction,
) -> CommandRequest:
    sql_text = _optional_str(namespace, "_sql")
    sql_file = _optional_path(namespace, "_sql_file")
    params_file = _optional_path(namespace, "_params_file")
    if sql_text is not None and sql_file is not None:
        raise CliFailure(
            code=ErrorCode.INVALID_ARGUMENT,
            message="--sql 与 --sql-file 不能同时使用",
            retryable=False,
            details=(
                ErrorDetail(error_type=DiagnosticErrorType.MUTUALLY_EXCLUSIVE_INPUTS, argument="--sql/--sql-file"),
            ),
            exit_code=ExitCode.INVALID_ARGUMENT,
        )
    if sql_text is None and sql_file is None:
        raise CliFailure(
            code=ErrorCode.INVALID_ARGUMENT,
            message="SQL 命令必须提供 --sql 或 --sql-file",
            retryable=False,
            details=(ErrorDetail(error_type=DiagnosticErrorType.MISSING_SQL, argument="--sql|--sql-file"),),
            exit_code=ExitCode.INVALID_ARGUMENT,
        )
    if sql_text is not None:
        sql_input = SqlInputSpec.inline(sql_text)
    elif sql_file == Path("-"):
        sql_input = SqlInputSpec.stdin()
    else:
        if sql_file is None:
            raise TypeError("SQL 文件路径缺失")
        sql_input = SqlInputSpec.file(sql_file)
    return CommandRequest(group=group, action=action, sql_input=sql_input, params_file=params_file)


def _required_group(namespace: argparse.Namespace) -> CommandGroup:
    value = getattr(namespace, "_command_group", None)
    if isinstance(value, CommandGroup):
        return value
    raise CliFailure(
        code=ErrorCode.INVALID_ARGUMENT,
        message="必须提供命令",
        retryable=False,
        details=(ErrorDetail(error_type=DiagnosticErrorType.ARGUMENT_SYNTAX),),
        exit_code=ExitCode.INVALID_ARGUMENT,
    )


def _required_action(namespace: argparse.Namespace) -> CommandAction:
    value = getattr(namespace, "_command_action", None)
    if isinstance(value, CommandAction):
        return value
    raise CliFailure(
        code=ErrorCode.INVALID_ARGUMENT,
        message="必须提供命令动作",
        retryable=False,
        details=(ErrorDetail(error_type=DiagnosticErrorType.ARGUMENT_SYNTAX),),
        exit_code=ExitCode.INVALID_ARGUMENT,
    )


def _optional_str(namespace: argparse.Namespace, name: str) -> str | None:
    value = getattr(namespace, name, None)
    if value is None or isinstance(value, str):
        return value
    raise TypeError(f"参数 {name} 类型无效")


def _optional_path(namespace: argparse.Namespace, name: str) -> Path | None:
    value = getattr(namespace, name, None)
    if value is None or isinstance(value, Path):
        return value
    raise TypeError(f"参数 {name} 类型无效")
