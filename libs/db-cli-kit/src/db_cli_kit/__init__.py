"""Shared, database-neutral mechanics for the ``db-*`` command line tools."""

from db_cli_kit.atomic_json import AtomicJsonError, AtomicJsonErrorReason, AtomicJsonStore
from db_cli_kit.json_codec import (
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
from db_cli_kit.profiles import (
    PROFILE_NAME_PATTERN,
    DirectoryBinding,
    ProfileName,
    normalize_directory,
)
from db_cli_kit.secrets import KeyringSecretStore, SecretStore, SecretStoreError
from db_cli_kit.stdio import TEXT_ENCODING, enforce_utf8_stdio

__all__ = [
    "PROFILE_NAME_PATTERN",
    "TEXT_ENCODING",
    "AtomicJsonError",
    "AtomicJsonErrorReason",
    "AtomicJsonStore",
    "DirectoryBinding",
    "JsonArray",
    "JsonDocumentError",
    "JsonObject",
    "JsonValue",
    "KeyringSecretStore",
    "ProfileName",
    "SecretStore",
    "SecretStoreError",
    "encode_json_document",
    "enforce_utf8_stdio",
    "is_json_array",
    "is_json_object",
    "is_json_value",
    "normalize_directory",
    "parse_json_document",
]
