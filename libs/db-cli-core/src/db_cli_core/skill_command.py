"""Discover the installed skill without adding it to normal command output."""

from pathlib import Path

import click

from db_cli_core.context import CommandContext
from db_cli_core.execution import execute_safely
from db_cli_core.output import emit_result
from mcp_base.types import ToolResult


def register_skill_command(root: click.Group, module_file: str, skill_name: str) -> None:
    group = click.Group("skill", help="按需定位当前 CLI 的使用技能")

    def path() -> None:
        context = click.get_current_context().find_object(CommandContext)
        if context is None:
            raise click.ClickException("CLI 上下文未初始化")

        def resolve() -> ToolResult:
            module = Path(module_file).resolve()
            packaged = module.parent / "skill" / "SKILL.md"
            candidates = [packaged, *(parent / "skills" / skill_name / "SKILL.md" for parent in module.parents)]
            for candidate in candidates:
                if candidate.is_file():
                    return ToolResult.success(data={"path": str(candidate)})
            raise FileNotFoundError("技能文件缺失, 请重新安装 CLI")

        emit_result(execute_safely(resolve), context.output_mode, context.profile_name)

    group.add_command(click.Command("path", callback=path, help="返回技能文件绝对路径"))
    root.add_command(group)
