"""Static argparse command tree and typed request construction."""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn

if TYPE_CHECKING:
    from collections.abc import Sequence

from mysql_cli import __version__
from mysql_cli.command_model import (
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
from mysql_cli.errors import CliFailure, ErrorDetail
from mysql_cli.profile_models import ProfileName, ProfileSettingsPatch
from mysql_client import DatabaseName, TableName, TransactionAction


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
            DiagnosticErrorType.UNKNOWN_COMMAND if "invalid choice" in message else DiagnosticErrorType.ARGUMENT_SYNTAX
        )
        code = (
            ErrorCode.UNKNOWN_COMMAND
            if error_type is DiagnosticErrorType.UNKNOWN_COMMAND
            else ErrorCode.INVALID_ARGUMENT
        )
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
    parser.add_argument("--json", action="store_true", help="emit one JSON document")
    parser.add_argument("--profile", dest="_selected_profile", help="select a profile for this invocation")
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
        if route.group is CommandGroup.PROFILE:
            _add_profile_arguments(action_parser, route.action)
        if route.group is CommandGroup.SCHEMA:
            _add_schema_arguments(action_parser, route.action)
        if route in SQL_ROUTES:
            _add_sql_arguments(action_parser, route.action)
    return parser


def parse_command_request(parser: argparse.ArgumentParser, argv: Sequence[str]) -> CommandRequest:
    """Parse argv into a typed request, applying input-source constraints."""

    namespace = parser.parse_args(list(argv))
    group = _required_group(namespace)
    action = _required_action(namespace)
    selected_profile = _profile_name(getattr(namespace, "_selected_profile", None), argument="--profile")
    if group is CommandGroup.HELP:
        return CommandRequest(group=group, action=action, selected_profile=selected_profile)
    if group is CommandGroup.SQL:
        request = _sql_request(namespace, group=group, action=action)
        return _with_selected_profile(request, selected_profile)
    if group is CommandGroup.PROFILE:
        return _profile_request(namespace, group=group, action=action, selected_profile=selected_profile)
    if group is CommandGroup.SCHEMA:
        return _schema_request(namespace, group=group, action=action, selected_profile=selected_profile)
    return CommandRequest(group=group, action=action, selected_profile=selected_profile)


def _add_profile_arguments(parser: argparse.ArgumentParser, action: CommandAction) -> None:
    if action in {
        CommandAction.SHOW,
        CommandAction.SET,
        CommandAction.VALIDATE,
        CommandAction.BIND,
        CommandAction.REMOVE,
    }:
        parser.add_argument("_profile_name_arg", metavar="NAME")
    elif action is CommandAction.RENAME:
        parser.add_argument("_profile_name_arg", metavar="OLD")
        parser.add_argument("_profile_new_name_arg", metavar="NEW")
    if action in {CommandAction.BIND, CommandAction.UNBIND}:
        parser.add_argument("--path", dest="_profile_path", type=Path)
    if action is CommandAction.SET:
        parser.add_argument("--host", dest="_host")
        parser.add_argument("--port", dest="_port", type=int)
        parser.add_argument("--user", dest="_user")
        parser.add_argument("--database", dest="_database")
        parser.add_argument("--no-database", dest="_no_database", action="store_true")
        parser.add_argument("--charset", dest="_charset")
        parser.add_argument("--connect-timeout", dest="_connect_timeout", type=float)
        parser.add_argument("--read-timeout", dest="_read_timeout", type=float)
        parser.add_argument("--password", dest="_password")
        parser.add_argument("--no-password", dest="_no_password", action="store_true")
        parser.add_argument("--no-bind", dest="_no_bind", action="store_true")


def _add_schema_arguments(parser: argparse.ArgumentParser, action: CommandAction) -> None:
    if action in {CommandAction.TABLES, CommandAction.DESCRIBE, CommandAction.INDEXES, CommandAction.STATS}:
        parser.add_argument(
            "--database",
            dest="_schema_database",
            help="schema name; default is the selected database",
        )
    if action in {CommandAction.DESCRIBE, CommandAction.INDEXES}:
        parser.add_argument("--table", dest="_schema_table", required=True, help="table name")
    elif action is CommandAction.STATS:
        parser.add_argument("--table", dest="_schema_table", help="optional table name")


def _add_sql_arguments(parser: argparse.ArgumentParser, action: CommandAction) -> None:
    if action is CommandAction.COMPARE:
        parser.add_argument("--left-sql", dest="_left_sql", help="left inline SQL text")
        parser.add_argument("--left-sql-file", dest="_left_sql_file", type=Path, help="left SQL file path")
        parser.add_argument("--right-sql", dest="_right_sql", help="right inline SQL text")
        parser.add_argument("--right-sql-file", dest="_right_sql_file", type=Path, help="right SQL file path")
        parser.add_argument("--left-params-file", dest="_left_params_file", type=Path, help="left JSON parameters")
        parser.add_argument("--right-params-file", dest="_right_params_file", type=Path, help="right JSON parameters")
        parser.add_argument("--key-column", dest="_key_columns", action="append", default=[])
        parser.add_argument("--max-diff-samples", dest="_max_diff_samples", type=int)
    else:
        parser.add_argument("--sql", dest="_sql", help="inline SQL text")
        parser.add_argument("--sql-file", dest="_sql_file", type=Path, help="SQL file path; - reads stdin")
        parser.add_argument("--params-file", dest="_params_file", type=Path, help="JSON object or array")
        if action is CommandAction.WRITE:
            parser.add_argument(
                "--transaction",
                dest="_transaction",
                choices=tuple(item.value for item in TransactionAction),
                default=TransactionAction.COMMIT.value,
                help="transaction decision: commit or rollback",
            )
        if action is CommandAction.READ:
            parser.add_argument("--max-rows", dest="_max_rows", type=int)
            parser.add_argument("--max-bytes", dest="_max_bytes", type=int)
        if action is CommandAction.BENCHMARK:
            parser.add_argument("--iterations", dest="_iterations", type=int)
            parser.add_argument("--warmup-iterations", dest="_warmup_iterations", type=int)
        parser.add_argument("--timeout", dest="_timeout", type=float, help="statement timeout in seconds")


def _profile_request(
    namespace: argparse.Namespace,
    *,
    group: CommandGroup,
    action: CommandAction,
    selected_profile: ProfileName | None,
) -> CommandRequest:
    name = _profile_name(getattr(namespace, "_profile_name_arg", None), argument="NAME")
    new_name = _profile_name(getattr(namespace, "_profile_new_name_arg", None), argument="NEW")
    required_name_actions = {
        CommandAction.SHOW,
        CommandAction.SET,
        CommandAction.VALIDATE,
        CommandAction.BIND,
        CommandAction.RENAME,
        CommandAction.REMOVE,
    }
    if action in required_name_actions and name is None:
        raise _profile_argument_failure("profile name is required", "NAME")
    if action is CommandAction.RENAME and new_name is None:
        raise _profile_argument_failure("new profile name is required", "NEW")
    patch = None
    password = _optional_str(namespace, "_password")
    clear_password = bool(getattr(namespace, "_no_password", False))
    no_bind = bool(getattr(namespace, "_no_bind", False))
    if action is CommandAction.SET:
        patch = ProfileSettingsPatch(
            host=_optional_str(namespace, "_host"),
            port=_optional_int(namespace, "_port"),
            user=_optional_str(namespace, "_user"),
            database=None if getattr(namespace, "_no_database", False) else _optional_str(namespace, "_database"),
            charset=_optional_str(namespace, "_charset"),
            connect_timeout=_optional_float(namespace, "_connect_timeout"),
            read_timeout=_optional_float(namespace, "_read_timeout"),
            clear_database=bool(getattr(namespace, "_no_database", False)),
        )
    return CommandRequest(
        group=group,
        action=action,
        selected_profile=selected_profile,
        profile_name=name,
        profile_new_name=new_name,
        profile_path=_optional_path(namespace, "_profile_path"),
        profile_settings=patch,
        profile_password=password,
        profile_clear_password=clear_password,
        profile_no_bind=no_bind,
    )


def _with_selected_profile(request: CommandRequest, selected_profile: ProfileName | None) -> CommandRequest:
    return replace(request, selected_profile=selected_profile)


def _schema_request(
    namespace: argparse.Namespace,
    *,
    group: CommandGroup,
    action: CommandAction,
    selected_profile: ProfileName | None,
) -> CommandRequest:
    return CommandRequest(
        group=group,
        action=action,
        selected_profile=selected_profile,
        schema_database=_database_name(getattr(namespace, "_schema_database", None)),
        schema_table=_table_name(getattr(namespace, "_schema_table", None)),
    )


def _sql_request(
    namespace: argparse.Namespace,
    *,
    group: CommandGroup,
    action: CommandAction,
) -> CommandRequest:
    if action is CommandAction.COMPARE:
        return _compare_request(namespace, group=group, action=action)
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
    transaction_value = getattr(namespace, "_transaction", TransactionAction.COMMIT.value)
    try:
        transaction = TransactionAction(transaction_value)
    except ValueError as exc:
        raise _sql_argument_failure("事务动作无效", "--transaction") from exc
    return CommandRequest(
        group=group,
        action=action,
        sql_input=sql_input,
        params_file=params_file,
        sql_max_rows=_optional_int(namespace, "_max_rows"),
        sql_max_bytes=_optional_int(namespace, "_max_bytes"),
        sql_timeout_seconds=_optional_float(namespace, "_timeout"),
        sql_iterations=_optional_int(namespace, "_iterations"),
        sql_warmup_iterations=_optional_int(namespace, "_warmup_iterations"),
        sql_transaction=transaction,
    )


def _compare_request(
    namespace: argparse.Namespace,
    *,
    group: CommandGroup,
    action: CommandAction,
) -> CommandRequest:
    left = _sql_spec(namespace, "_left_sql", "_left_sql_file", label="left SQL")
    right = _sql_spec(namespace, "_right_sql", "_right_sql_file", label="right SQL")
    key_columns = tuple(_string_list(namespace, "_key_columns"))
    max_diff_samples = _optional_int(namespace, "_max_diff_samples")
    timeout = _optional_float(namespace, "_timeout")
    if max_diff_samples is not None and max_diff_samples < 0:
        raise _sql_argument_failure("最大差异样本数不能为负数", "--max-diff-samples")
    return CommandRequest(
        group=group,
        action=action,
        compare_left_sql_input=left,
        compare_right_sql_input=right,
        compare_left_params_file=_optional_path(namespace, "_left_params_file"),
        compare_right_params_file=_optional_path(namespace, "_right_params_file"),
        compare_key_columns=key_columns,
        compare_max_diff_samples=max_diff_samples,
        sql_timeout_seconds=timeout,
    )


def _sql_spec(namespace: argparse.Namespace, text_name: str, file_name: str, *, label: str) -> SqlInputSpec:
    sql_text = _optional_str(namespace, text_name)
    sql_file = _optional_path(namespace, file_name)
    if sql_text is not None and sql_file is not None:
        raise _sql_argument_failure(f"{label}不能同时使用文本和文件", f"{text_name}/{file_name}")
    if sql_text is not None:
        return SqlInputSpec.inline(sql_text)
    if sql_file is not None:
        if sql_file == Path("-"):
            raise _sql_argument_failure("compare 不支持两个 SQL 输入共享标准输入", file_name)
        return SqlInputSpec.file(sql_file)
    raise _sql_argument_failure(f"必须提供 {label}", f"{text_name}|{file_name}")


def _string_list(namespace: argparse.Namespace, name: str) -> list[str]:
    value = getattr(namespace, name, [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise TypeError(f"参数 {name} 类型无效")
    return value


def _sql_argument_failure(message: str, argument: str) -> CliFailure:
    return CliFailure(
        code=ErrorCode.INVALID_ARGUMENT,
        message=message,
        retryable=False,
        details=(ErrorDetail(error_type=DiagnosticErrorType.ARGUMENT_SYNTAX, argument=argument),),
        exit_code=ExitCode.INVALID_ARGUMENT,
    )


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


def _optional_int(namespace: argparse.Namespace, name: str) -> int | None:
    value = getattr(namespace, name, None)
    if value is None or isinstance(value, int):
        return value
    raise TypeError(f"参数 {name} 类型无效")


def _optional_float(namespace: argparse.Namespace, name: str) -> float | None:
    value = getattr(namespace, name, None)
    if value is None or isinstance(value, float):
        return value
    raise TypeError(f"参数 {name} 类型无效")


def _profile_name(value: object, *, argument: str) -> ProfileName | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"参数 {argument} 类型无效")
    try:
        return ProfileName(value=value)
    except ValueError as exc:
        raise CliFailure(
            code=ErrorCode.INVALID_ARGUMENT,
            message="profile name is invalid",
            retryable=False,
            details=(ErrorDetail(error_type=DiagnosticErrorType.ARGUMENT_SYNTAX, argument=argument),),
            exit_code=ExitCode.INVALID_ARGUMENT,
        ) from exc


def _profile_argument_failure(message: str, argument: str) -> CliFailure:
    return CliFailure(
        code=ErrorCode.INVALID_ARGUMENT,
        message=message,
        retryable=False,
        details=(ErrorDetail(error_type=DiagnosticErrorType.ARGUMENT_SYNTAX, argument=argument),),
        exit_code=ExitCode.INVALID_ARGUMENT,
    )


def _optional_path(namespace: argparse.Namespace, name: str) -> Path | None:
    value = getattr(namespace, name, None)
    if value is None or isinstance(value, Path):
        return value
    raise TypeError(f"参数 {name} 类型无效")


def _database_name(value: object) -> DatabaseName | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("参数 --database 类型无效")
    try:
        return DatabaseName(value=value)
    except ValueError as exc:
        raise _schema_argument_failure("数据库名无效", "--database") from exc


def _table_name(value: object) -> TableName | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("参数 --table 类型无效")
    try:
        return TableName(value=value)
    except ValueError as exc:
        raise _schema_argument_failure("表名无效", "--table") from exc


def _schema_argument_failure(message: str, argument: str) -> CliFailure:
    return CliFailure(
        code=ErrorCode.INVALID_ARGUMENT,
        message=message,
        retryable=False,
        details=(ErrorDetail(error_type=DiagnosticErrorType.ARGUMENT_SYNTAX, argument=argument),),
        exit_code=ExitCode.INVALID_ARGUMENT,
    )
