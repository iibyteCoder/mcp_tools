"""Click command group for managing profiles exclusively through the CLI."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import click

from db_cli_core.context import CommandContext
from db_cli_core.enums import ProfileCommand
from db_cli_core.execution import execute_safely
from db_cli_core.output import emit_result
from mcp_base.types import ToolResult


def register_profile_commands(root: click.Group, connection_options: list[click.Option]) -> None:
    group = click.Group(ProfileCommand.GROUP.value, help="管理命名连接和按目录自动选择")
    group.add_command(_set_command(connection_options))
    group.add_command(
        click.Command(
            ProfileCommand.RENAME.value,
            params=[click.Argument(["name"]), click.Argument(["new_name"])],
            callback=_rename_profile,
            help="重命名连接, 保留设置、密码和全部目录绑定",
        )
    )
    group.add_command(click.Command(ProfileCommand.LIST.value, callback=_list_profiles, help="列出命名连接"))
    group.add_command(
        click.Command(
            ProfileCommand.SHOW.value,
            params=[click.Argument(["name"])],
            callback=_show_profile,
            help="查看一个命名连接",
        )
    )
    group.add_command(
        click.Command(
            ProfileCommand.SELECT.value,
            params=[click.Argument(["name"]), _path_option()],
            callback=_select_profile,
            help="将目录绑定到已有连接",
        )
    )
    group.add_command(
        click.Command(
            ProfileCommand.CURRENT.value,
            params=[_path_option()],
            callback=_current_profile,
            help="查看目录实际选中的连接",
        )
    )
    group.add_command(
        click.Command(
            ProfileCommand.REMOVE.value,
            params=[click.Argument(["name"])],
            callback=_remove_profile,
            help="删除连接及其全部目录绑定",
        )
    )
    group.add_command(
        click.Command(
            ProfileCommand.CLEAR.value,
            params=[_path_option()],
            callback=_clear_binding,
            help="解除目录的直接绑定",
        )
    )
    root.add_command(group)


def _set_command(connection_options: list[click.Option]) -> click.Command:
    parameters: list[click.Parameter] = [
        click.Argument(["name"]),
        *connection_options,
        _path_option(),
        click.Option(["--no-bind"], is_flag=True, help="只保存命名连接, 不绑定目录"),
    ]
    return click.Command(
        ProfileCommand.SET.value,
        params=parameters,
        callback=_set_profile,
        help="创建或更新连接; 默认同时绑定目录",
    )


def _set_profile(name: str, path: Path, no_bind: bool, **settings: Any) -> None:
    context = _context()

    def operation() -> ToolResult:
        manager = _manager(context)
        existing = manager.find(name)
        context.activate(None)
        if existing is not None:
            context.backend.configure(**existing.settings)
        complete_settings = context.backend.build_profile(**settings)
        selection = manager.set(name, complete_settings, None if no_bind else path)
        context.activate(selection)
        return ToolResult.success(
            message=f"已保存连接配置 {name}",
            data={"config_file": str(manager.store.path), "bound": not no_bind},
        )

    _emit(context, execute_safely(operation))


def _list_profiles() -> None:
    context = _context()

    def operation() -> ToolResult:
        manager = _manager(context)
        return ToolResult.success(
            data={"profiles": [profile.name for profile in manager.profiles()], "config_file": str(manager.store.path)}
        )

    _emit(context, execute_safely(operation))


def _show_profile(name: str) -> None:
    context = _context()

    def operation() -> ToolResult:
        manager = _manager(context)
        selection = manager.resolve(profile_name=name)
        context.activate(selection)
        return ToolResult.success(data=context.connection_info())

    _emit(context, execute_safely(operation))


def _select_profile(name: str, path: Path) -> None:
    context = _context()

    def operation() -> ToolResult:
        selection = _manager(context).select(name, path)
        context.activate(selection)
        return ToolResult.success(message=f"目录已切换到连接配置 {name}", data={"directory": str(path.resolve())})

    _emit(context, execute_safely(operation))


def _current_profile(path: Path) -> None:
    context = _context()

    def operation() -> ToolResult:
        context.activate(_manager(context).resolve(directory=path))
        return ToolResult.success(data=context.connection_info())

    _emit(context, execute_safely(operation))


def _remove_profile(name: str) -> None:
    context = _context()

    def operation() -> ToolResult:
        _manager(context).remove(name)
        if context.selection and context.selection.profile.name == name:
            context.activate(None)
        return ToolResult.success(message=f"已删除连接配置 {name}")

    _emit(context, execute_safely(operation))


def _rename_profile(name: str, new_name: str) -> None:
    context = _context()

    def operation() -> ToolResult:
        manager = _manager(context)
        manager.rename(name, new_name)
        context.activate(manager.resolve(profile_name=new_name))
        return ToolResult.success(message=f"已重命名连接配置为 {new_name.strip()}")

    _emit(context, execute_safely(operation))


def _clear_binding(path: Path) -> None:
    context = _context()

    def operation() -> ToolResult:
        _manager(context).clear(path)
        context.activate(_manager(context).resolve(directory=path))
        return ToolResult.success(message=f"已解除目录绑定 {path.resolve()}")

    _emit(context, execute_safely(operation))


def _context() -> CommandContext:
    context = click.get_current_context().find_object(CommandContext)
    if context is None:
        raise click.ClickException("CLI 上下文未初始化")
    return context


def _manager(context: CommandContext):  # type: ignore[no-untyped-def]
    if context.profile_manager is None:
        raise ValueError("连接配置管理器未初始化")
    return context.profile_manager


def _emit(context: CommandContext, result: ToolResult) -> None:
    emit_result(result, context.output_mode, context.profile_name)


def _path_option() -> click.Option:
    return click.Option(
        ["--path"],
        type=click.Path(path_type=Path, file_okay=False, resolve_path=True),
        default=Path("."),
        show_default=True,
        help="要绑定或解析的目录",
    )
