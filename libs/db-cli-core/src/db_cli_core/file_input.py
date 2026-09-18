"""Alternative UTF-8 file/stdin input for SQL and pipeline commands."""

import json
from pathlib import Path
from typing import Any

import click


def resolve_file_input(arguments: dict[str, Any], field: str) -> None:
    filename = arguments.pop(f"{field}_file", None)
    inline = arguments.get(field)
    if filename is not None and inline is not None:
        raise click.UsageError(f"--{field} 与 --{field}-file 不能同时使用")
    if filename is None and inline is None:
        raise click.UsageError(f"必须提供 --{field} 或 --{field}-file")
    try:
        value = inline
        if filename is not None:
            value = (
                click.get_text_stream("stdin").read()
                if filename == "-"
                else Path(filename).read_text(encoding="utf-8-sig")
            )
            if field == "commands":
                value = json.loads(value)
        if field == "commands":
            if (
                not isinstance(value, list)
                or not value
                or any(
                    not isinstance(command, list) or not command or any(not isinstance(arg, str) for arg in command)
                    for command in value
                )
            ):
                raise ValueError("commands 必须是非空字符串数组组成的非空数组")
        elif not isinstance(value, str) or not value.strip():
            raise ValueError("SQL 不能为空")
        arguments[field] = value
    except (OSError, ValueError) as exc:
        raise click.BadParameter(str(exc), param_hint=f"--{field}-file" if filename else f"--{field}") from exc
