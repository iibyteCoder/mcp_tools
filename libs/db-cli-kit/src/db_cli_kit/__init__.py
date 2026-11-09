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

__all__ = [
    "PROFILE_NAME_PATTERN",
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
    "is_json_array",
    "is_json_object",
    "is_json_value",
    "normalize_directory",
    "parse_json_document",
]
