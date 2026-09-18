"""Types exchanged through the shared CLI interface."""

from __future__ import annotations

from typing import Any, TypeAlias

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
Arguments: TypeAlias = dict[str, Any]
