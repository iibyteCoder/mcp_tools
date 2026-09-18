"""MySQL CLI composition root."""

from __future__ import annotations

from pathlib import Path

import click

from db_cli_core import CommandContext, register_catalog, register_profile_commands
from db_cli_core.command_group import AgentGroup
from db_cli_core.connection_options import ConnectionOptionSpec, build_connection_options, connection_options
from db_cli_core.connection_setup import configure_command_context
from db_cli_core.enums import DatabaseKind
from db_cli_core.execution import execute_safely
from db_cli_core.output import emit_result
from db_cli_core.profiles import ConnectionProfileManager
from db_cli_core.repl import run_repl
from db_cli_core.skill_command import register_skill_command
from mysql_cli import __version__
from mysql_cli.backend import MySQLBackend
from mysql_cli.catalog import build_catalog
from mysql_cli.enums import MySQLApplication

MYSQL_CONNECTION_OPTIONS = (
    ConnectionOptionSpec(("--url",), "MySQL URL, 例如 mysql://root:pwd@localhost:3306/app"),
    ConnectionOptionSpec(("--host",), "MySQL 主机; 覆盖环境变量和 URL"),
    ConnectionOptionSpec(("--port",), "MySQL 端口", click.IntRange(1, 65535)),
    ConnectionOptionSpec(("--user",), "MySQL 用户"),
    ConnectionOptionSpec(("--password",), "MySQL 密码; 由系统凭据库保存"),
    ConnectionOptionSpec(("--database",), "当前数据库"),
    ConnectionOptionSpec(("--charset",), "连接字符集"),
    ConnectionOptionSpec(("--connection-timeout",), "连接超时秒数", click.IntRange(min=1)),
)


@click.group(cls=AgentGroup, invoke_without_command=True)
@click.option("--json", "use_json", is_flag=True, help="输出单行、机器可读的 JSON")
@click.option("--profile", "profile_name", help="临时使用指定命名连接, 不改变目录绑定")
@connection_options(MYSQL_CONNECTION_OPTIONS)
@click.version_option(__version__)
@click.pass_context
def cli(
    click_context: click.Context,
    /,
    use_json: bool,
    profile_name: str | None,
    **connection_settings: object,
) -> None:
    """操作真实 MySQL 服务; 无子命令时进入交互模式。"""
    command_context = click_context.find_object(CommandContext)
    if command_context is None:
        command_context = CommandContext(MySQLBackend(), profile_manager=ConnectionProfileManager(DatabaseKind.MYSQL))
        click_context.obj = command_context
    manager = command_context.profile_manager or ConnectionProfileManager(DatabaseKind.MYSQL)
    backend = command_context.backend
    if not isinstance(backend, MySQLBackend):
        raise click.ClickException("MySQL CLI 收到了不兼容的后端")
    configure_command_context(command_context, manager, profile_name, connection_settings, use_json)
    if click_context.invoked_subcommand is None:
        history_path = str(Path.home() / MySQLApplication.HISTORY_FILE.value)
        run_repl(cli, command_context, MySQLApplication.NAME.value, history_path)


@cli.command(MySQLApplication.USE_COMMAND.value)
@click.argument("database")
@click.pass_obj
def use_database(command_context: CommandContext, database: str) -> None:
    """切换数据库, 并在交互模式中保持连接池。"""
    result = execute_safely(lambda: command_context.backend.switch_target(database))
    emit_result(result, command_context.output_mode, command_context.profile_name)


register_skill_command(cli, __file__, "mysql-cli")
register_catalog(cli, build_catalog())
register_profile_commands(cli, build_connection_options(MYSQL_CONNECTION_OPTIONS))


def main() -> None:
    backend = MySQLBackend()
    try:
        cli(obj=CommandContext(backend, profile_manager=ConnectionProfileManager(DatabaseKind.MYSQL)))
    finally:
        backend.close()


if __name__ == "__main__":
    main()
