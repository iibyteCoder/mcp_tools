"""Structured and human-readable output rendering."""

import json
import math
from typing import Any

import click

from db_cli_core.enums import OutputMode
from mcp_base.types import ToolResult, ToolStatus


def json_value(value: Any) -> Any:
    """Retain JSON types while representing nonfinite database numbers legally."""
    if isinstance(value, float) and not math.isfinite(value):
        return "NaN" if math.isnan(value) else ("Infinity" if value > 0 else "-Infinity")
    if isinstance(value, dict):
        return {key: json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    return value


def emit_result(result: ToolResult, output_mode: OutputMode, profile: str | None = None) -> None:
    payload = result.to_dict()
    payload["profile"] = profile
    if result.status is ToolStatus.SUCCESS and result.data is not None:
        payload.pop("message", None)
    elif result.status is ToolStatus.ERROR:
        payload.setdefault("code", "EXECUTION_FAILED")
    if output_mode is OutputMode.JSON:
        click.echo(json.dumps(json_value(payload), ensure_ascii=False, default=str, allow_nan=False))
    else:
        if payload.get("message"):
            click.echo(payload["message"])
        if result.data is not None:
            click.echo(json.dumps(json_value(result.data), ensure_ascii=False, indent=2, default=str, allow_nan=False))
        click.echo(f"profile: {profile or '(unnamed)'}")
    if result.status is ToolStatus.ERROR:
        raise click.exceptions.Exit(1)
