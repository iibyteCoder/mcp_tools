"""Conversion and clipping helpers at the Redis/JSON boundary."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from redis_cli.enums import RedisKeyType

if TYPE_CHECKING:
    from redis_cli.json_types import JsonValue


@dataclass(frozen=True, slots=True)
class BytePreview:
    """A UTF-8-safe preview bounded by bytes rather than characters."""

    text: str
    truncated: bool


@dataclass(frozen=True, slots=True)
class PipelineCommand:
    """One user-supplied Redis pipeline command."""

    name: str
    arguments: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PipelineRequest:
    """Validated pipeline input."""

    commands: tuple[PipelineCommand, ...]


def to_text(value: object) -> str:
    """Decode Redis bytes deterministically for JSON output."""

    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def to_integer(value: object) -> int:
    """Convert a Redis numeric response at the typed boundary."""

    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, (str, bytes, bytearray)):
        return int(value)
    raise TypeError(f"Expected an integer response, got {type(value).__name__}")


def to_number(value: object) -> float:
    """Convert a Redis floating-point response at the typed boundary."""

    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, (str, bytes, bytearray)):
        return float(value)
    raise TypeError(f"Expected a numeric response, got {type(value).__name__}")


def to_json_value(value: object) -> JsonValue:
    """Convert Redis responses into JSON-safe named boundary values."""

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, bytes):
        return to_text(value)
    if isinstance(value, float):
        if math.isfinite(value):
            return value
        if math.isnan(value):
            return "NaN"
        return "Infinity" if value > 0 else "-Infinity"
    if isinstance(value, (list, tuple)):
        return [to_json_value(item) for item in value]
    if isinstance(value, Mapping):
        return {to_text(key): to_json_value(item) for key, item in value.items()}
    return str(value)


def byte_preview(value: object, limit: int) -> BytePreview:
    """Clip text by encoded byte length while preserving valid UTF-8 output."""

    if limit < 0:
        raise ValueError("preview limit must be nonnegative")
    text = to_text(value)
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return BytePreview(text=text, truncated=False)
    clipped = encoded[:limit].decode("utf-8", errors="ignore")
    return BytePreview(text=clipped, truncated=True)


def key_type(value: object) -> RedisKeyType:
    """Map Redis TYPE output to a stable enum."""

    raw = to_text(value)
    for item in RedisKeyType:
        if item.value == raw:
            return item
    return RedisKeyType.UNKNOWN


__all__ = [
    "BytePreview",
    "PipelineCommand",
    "PipelineRequest",
    "byte_preview",
    "key_type",
    "to_integer",
    "to_json_value",
    "to_number",
    "to_text",
]
