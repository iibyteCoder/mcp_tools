"""Versioned, atomic and locked persistence for the DM profile registry."""

from __future__ import annotations

import math
from pathlib import Path
from typing import TYPE_CHECKING, Final

from platformdirs import user_config_path

from db_cli_kit.atomic_json import AtomicJsonError, AtomicJsonErrorReason, AtomicJsonStore
from db_cli_kit.json_codec import JsonObject, JsonValue, is_json_object
from db_cli_kit.profiles import DirectoryBinding, ProfileName
from dm_cli.domain.profile import (
    ProfileRecord,
    ProfileRegistry,
    ProfileSettings,
    RegistryErrorCode,
)
from dm_cli.ports.profile_store import ProfileStore, ProfileStoreError

if TYPE_CHECKING:
    from collections.abc import Callable

APP_DIRECTORY: Final[str] = "db-dm"
FILE_NAME: Final[str] = "profiles.json"
SCHEMA: Final[str] = "db-dm.profile-registry"
VERSION: Final[int] = 1
CLI_LOCK_TIMEOUT_SECONDS: Final[float] = 1.0

TOP_LEVEL_KEYS = frozenset({"schema", "version", "profiles", "bindings"})
PROFILE_KEYS = frozenset({"name", "settings", "description", "password_present"})
SETTINGS_KEYS = frozenset({"host", "port", "user", "schema", "connect_timeout", "query_timeout"})
BINDING_KEYS = frozenset({"path", "profile"})


class JsonProfileStore:
    """Persist the DM profile registry as one versioned JSON document."""

    SCHEMA: Final[str] = SCHEMA
    VERSION: Final[int] = VERSION
    CLI_LOCK_TIMEOUT_SECONDS: Final[float] = CLI_LOCK_TIMEOUT_SECONDS

    def __init__(self, path: Path | None = None, *, lock_timeout: float = CLI_LOCK_TIMEOUT_SECONDS) -> None:
        self.path = path or (user_config_path(APP_DIRECTORY) / FILE_NAME)
        self._store = AtomicJsonStore(self.path, lock_timeout)

    def read(self) -> ProfileRegistry:
        try:
            document = self._store.read()
        except AtomicJsonError as exc:
            raise _translate(exc) from exc
        return ProfileRegistry() if document is None else _registry_from_document(document)

    def write(self, registry: ProfileRegistry) -> None:
        document = _registry_to_document(registry)
        try:
            self._store.write(document)
        except AtomicJsonError as exc:
            raise _translate(exc) from exc

    def update(self, updater: Callable[[ProfileRegistry], ProfileRegistry]) -> ProfileRegistry:
        updated: list[ProfileRegistry] = []

        def apply(document: JsonObject | None) -> JsonObject:
            current = ProfileRegistry() if document is None else _registry_from_document(document)
            registry = updater(current)
            updated.append(registry)
            return _registry_to_document(registry)

        try:
            self._store.update(apply)
        except AtomicJsonError as exc:
            raise _translate(exc) from exc
        if not updated:
            raise RuntimeError("profile registry update did not produce a document")
        return updated[0]


def _translate(error: AtomicJsonError) -> ProfileStoreError:
    mapping = {
        AtomicJsonErrorReason.CORRUPT: RegistryErrorCode.CORRUPT,
        AtomicJsonErrorReason.LOCKED: RegistryErrorCode.LOCKED,
        AtomicJsonErrorReason.IO: RegistryErrorCode.IO,
    }
    return ProfileStoreError(mapping[error.reason], error.message)


def _registry_to_document(registry: ProfileRegistry) -> JsonObject:
    profiles: list[JsonValue] = []
    for record in registry.profiles:
        profiles.append(
            {
                "name": record.name.value,
                "settings": {
                    "host": record.settings.host,
                    "port": record.settings.port,
                    "user": record.settings.user,
                    "schema": record.settings.schema,
                    "connect_timeout": record.settings.connect_timeout,
                    "query_timeout": record.settings.query_timeout,
                },
                "description": record.description,
                "password_present": record.password_present,
            }
        )
    bindings: list[JsonValue] = [
        {"path": str(binding.path), "profile": binding.profile.value} for binding in registry.bindings
    ]
    return {
        "schema": SCHEMA,
        "version": VERSION,
        "profiles": profiles,
        "bindings": bindings,
    }


def _registry_from_document(document: JsonObject) -> ProfileRegistry:
    if set(document) != TOP_LEVEL_KEYS:
        raise ProfileStoreError(RegistryErrorCode.CORRUPT, "profile registry schema is invalid")
    if document.get("schema") != SCHEMA:
        raise ProfileStoreError(RegistryErrorCode.CORRUPT, "profile registry schema is invalid")
    version = document.get("version")
    if isinstance(version, bool) or not isinstance(version, int):
        raise ProfileStoreError(RegistryErrorCode.CORRUPT, "profile registry version is invalid")
    if version != VERSION:
        raise ProfileStoreError(
            RegistryErrorCode.UNSUPPORTED_VERSION, "profile registry version is unsupported"
        )
    profiles_value = document.get("profiles")
    bindings_value = document.get("bindings")
    if not isinstance(profiles_value, list) or not isinstance(bindings_value, list):
        raise ProfileStoreError(RegistryErrorCode.CORRUPT, "profile registry schema is invalid")
    try:
        profiles = tuple(_profile_from_document(item) for item in profiles_value)
        bindings = tuple(_binding_from_document(item) for item in bindings_value)
        return ProfileRegistry(profiles=profiles, bindings=bindings)
    except ProfileStoreError:
        raise
    except (TypeError, ValueError, KeyError) as exc:
        raise ProfileStoreError(RegistryErrorCode.CORRUPT, "profile registry schema is invalid") from exc


def _profile_from_document(value: JsonValue) -> ProfileRecord:
    if not is_json_object(value) or set(value) != PROFILE_KEYS:
        raise ProfileStoreError(RegistryErrorCode.CORRUPT, "profile record is invalid")
    settings_value = value.get("settings")
    if not is_json_object(settings_value) or set(settings_value) != SETTINGS_KEYS:
        raise ProfileStoreError(RegistryErrorCode.CORRUPT, "profile settings are invalid")
    password_present = value.get("password_present")
    if not isinstance(password_present, bool):
        raise ProfileStoreError(RegistryErrorCode.CORRUPT, "profile password metadata is invalid")
    return ProfileRecord(
        name=ProfileName(value=_string(value, "name")),
        settings=ProfileSettings(
            host=_string(settings_value, "host"),
            port=_int(settings_value, "port"),
            user=_string(settings_value, "user"),
            schema=_optional_string(settings_value, "schema"),
            connect_timeout=_number(settings_value, "connect_timeout"),
            query_timeout=_number(settings_value, "query_timeout"),
        ),
        description=_optional_string(value, "description"),
        password_present=password_present,
    )


def _binding_from_document(value: JsonValue) -> DirectoryBinding:
    if not is_json_object(value) or set(value) != BINDING_KEYS:
        raise ProfileStoreError(RegistryErrorCode.CORRUPT, "directory binding is invalid")
    return DirectoryBinding(
        path=Path(_string(value, "path")),
        profile=ProfileName(value=_string(value, "profile")),
    )


def _string(value: JsonObject, key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str):
        raise ProfileStoreError(RegistryErrorCode.CORRUPT, f"profile registry field {key} is invalid")
    return item


def _optional_string(value: JsonObject, key: str) -> str | None:
    item = value.get(key)
    if item is None or isinstance(item, str):
        return item
    raise ProfileStoreError(RegistryErrorCode.CORRUPT, f"profile registry field {key} is invalid")


def _int(value: JsonObject, key: str) -> int:
    item = value.get(key)
    if isinstance(item, bool) or not isinstance(item, int):
        raise ProfileStoreError(RegistryErrorCode.CORRUPT, f"profile registry field {key} is invalid")
    return item


def _number(value: JsonObject, key: str) -> float:
    item = value.get(key)
    if isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(float(item)):
        raise ProfileStoreError(RegistryErrorCode.CORRUPT, f"profile registry field {key} is invalid")
    return float(item)


__all__ = [
    "APP_DIRECTORY",
    "CLI_LOCK_TIMEOUT_SECONDS",
    "FILE_NAME",
    "SCHEMA",
    "VERSION",
    "JsonProfileStore",
    "ProfileStore",
    "ProfileStoreError",
]
