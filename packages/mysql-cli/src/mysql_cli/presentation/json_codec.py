"""Compatibility imports for the shared JSON codec."""

from mysql_cli.shared.json_codec import (
    JsonArray,
    JsonDocumentError,
    JsonObject,
    JsonValue,
    encode_json_document,
    is_json_array,
    is_json_object,
    is_json_value,
    parse_json_document,
)

__all__ = [
    "JsonArray",
    "JsonDocumentError",
    "JsonObject",
    "JsonValue",
    "encode_json_document",
    "is_json_array",
    "is_json_object",
    "is_json_value",
    "parse_json_document",
]
