"""Translate MCP JSON schema properties into Click options."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import click

from db_cli_core.enums import JsonSchemaType

if TYPE_CHECKING:
    from collections.abc import Mapping

    from db_cli_core.types import Arguments


def build_options(input_schema: Mapping[str, Any]) -> list[click.Option]:
    required_names = set(input_schema.get("required", []))
    return [
        _build_option(property_name, property_schema, property_name in required_names)
        for property_name, property_schema in input_schema.get("properties", {}).items()
    ]


def normalize_arguments(arguments: Arguments) -> Arguments:
    return {
        name: list(value) if isinstance(value, tuple) else value
        for name, value in arguments.items()
        if value is not None
    }


def _build_option(property_name: str, schema: Mapping[str, Any], required: bool) -> click.Option:
    option_name = f"--{property_name.replace('_', '-')}"
    schema_type = JsonSchemaType(schema.get("type", JsonSchemaType.STRING.value))
    attributes: dict[str, Any] = {"help": schema.get("description", ""), "required": required}

    if schema_type is JsonSchemaType.INTEGER:
        attributes["type"] = int
    elif schema_type is JsonSchemaType.NUMBER:
        attributes["type"] = float
    elif schema_type is JsonSchemaType.BOOLEAN:
        attributes.update(is_flag=True, default=False)
        attributes.pop("required")
    elif schema_type is JsonSchemaType.ARRAY:
        item_type = JsonSchemaType(schema.get("items", {}).get("type", JsonSchemaType.STRING.value))
        if item_type in {JsonSchemaType.ARRAY, JsonSchemaType.OBJECT}:
            attributes["callback"] = _parse_json_array
        else:
            attributes.update(multiple=True, type=str)
    elif schema_type is JsonSchemaType.OBJECT:
        attributes["callback"] = _parse_json_object
    else:
        attributes["type"] = str
    return click.Option([option_name], **attributes)


def _parse_json_object(_context: click.Context, _parameter: click.Parameter, value: str | None) -> Any:
    if value is None:
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise click.BadParameter(f"不是有效 JSON: {exc.msg}") from exc
    if not isinstance(parsed, dict):
        raise click.BadParameter("必须是 JSON object")
    return parsed


def _parse_json_array(_context: click.Context, _parameter: click.Parameter, value: str | None) -> Any:
    if value is None:
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise click.BadParameter(f"不是有效 JSON: {exc.msg}") from exc
    if not isinstance(parsed, list):
        raise click.BadParameter("必须是 JSON array")
    return parsed
