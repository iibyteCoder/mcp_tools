"""Explicit JSON encoding and decoding for the CLI contract."""

from __future__ import annotations

import base64
import json
from dataclasses import fields, is_dataclass
from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import TypeAlias, TypeGuard, cast

JsonValue: TypeAlias = bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"] | None
JsonObject: TypeAlias = dict[str, JsonValue]
JsonArray: TypeAlias = list[JsonValue]


class JsonDocumentError(ValueError):
    """Raised when input is not a supported JSON document."""


def is_json_value(value: object) -> TypeGuard[JsonValue]:
    """Return whether a runtime value is recursively JSON-compatible."""

    if value is None or isinstance(value, (bool, int, float, str)):
        return True
    if isinstance(value, list):
        return all(is_json_value(item) for item in value)
    if isinstance(value, dict):
        return all(isinstance(key, str) and is_json_value(item) for key, item in value.items())
    return False


def is_json_object(value: JsonValue) -> TypeGuard[JsonObject]:
    """Return whether a JSON value is an object."""

    return isinstance(value, dict)


def is_json_array(value: JsonValue) -> TypeGuard[JsonArray]:
    """Return whether a JSON value is an array."""

    return isinstance(value, list)


def parse_json_document(text: str) -> JsonValue:
    """Parse standard JSON and reject non-finite numeric constants."""

    try:
        loaded: object = cast("object", json.loads(text, parse_constant=_reject_constant))
    except (json.JSONDecodeError, ValueError) as exc:
        raise JsonDocumentError("JSON 文档解析失败") from exc
    if not is_json_value(loaded):
        raise JsonDocumentError("JSON 文档包含不支持的值")
    return loaded


def encode_json_document(value: object) -> str:
    """Encode supported values without implicit ``str`` fallbacks."""

    encoded = _to_json_value(value)
    return json.dumps(encoded, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n"


def _reject_constant(value: str) -> None:
    raise ValueError(f"非标准 JSON 数字常量: {value}")


def _to_json_value(value: object) -> JsonValue:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Enum):
        return _to_json_value(value.value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bytes):
        return base64.b64encode(value).decode("ascii")
    if is_dataclass(value):
        return {
            field.name: _to_json_value(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, (list, tuple)):
        return [_to_json_value(item) for item in value]
    if isinstance(value, dict):
        result: JsonObject = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("JSON object keys must be strings")
            result[key] = _to_json_value(item)
        return result
    raise TypeError(f"不支持 JSON 序列化类型: {type(value).__name__}")
