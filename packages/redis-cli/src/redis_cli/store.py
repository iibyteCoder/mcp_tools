"""Locked, atomic persistence for Redis profile metadata."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, cast

from platformdirs import user_config_path

from db_cli_kit.atomic_json import AtomicJsonError, AtomicJsonErrorReason, AtomicJsonStore
from db_cli_kit.json_codec import JsonObject, JsonValue, is_json_object
from db_cli_kit.profiles import DirectoryBinding, ProfileName
from redis_cli.constants import PROFILE_REGISTRY_DIRECTORY, PROFILE_REGISTRY_FILE_NAME, PROFILE_REGISTRY_VERSION
from redis_cli.domain.errors import RedisCliError
from redis_cli.domain.profiles import ProfileRecord, ProfileRegistry, RedisSettings
from redis_cli.enums import ErrorCode, RegistrySchema
from redis_cli.json_types import BindingDocument, ProfileDocument, RegistryDocument, SettingsDocument

if TYPE_CHECKING:
    from collections.abc import Callable


class JsonProfileStore:
    """Persist profiles under ``%APPDATA%/db-cli/connections.json``."""

    SCHEMA = RegistrySchema.REDIS_CONNECTIONS.value
    VERSION = PROFILE_REGISTRY_VERSION
    LOCK_TIMEOUT_SECONDS = 1.0

    def __init__(self, path: Path | None = None, *, lock_timeout: float = 0.0) -> None:
        self.path = path or (user_config_path(PROFILE_REGISTRY_DIRECTORY) / PROFILE_REGISTRY_FILE_NAME)
        self.lock_timeout = lock_timeout
        self._store = AtomicJsonStore(self.path, lock_timeout)
        self.lock_path = self._store.lock_path

    def read(self) -> ProfileRegistry:
        try:
            document = self._store.read()
        except AtomicJsonError as exc:
            raise _read_error(exc) from exc
        return ProfileRegistry() if document is None else _registry_from_document(document)

    def update(self, updater: Callable[[ProfileRegistry], ProfileRegistry]) -> ProfileRegistry:
        updated: list[ProfileRegistry] = []
        reading = True

        def apply(document: JsonObject | None) -> JsonObject:
            nonlocal reading
            reading = False
            current = ProfileRegistry() if document is None else _registry_from_document(document)
            registry = updater(current)
            updated.append(registry)
            return cast("JsonObject", _registry_to_document(registry))

        try:
            self._store.update(apply)
        except AtomicJsonError as exc:
            raise (_read_error(exc) if reading else _write_error(exc)) from exc
        return updated[0]


def _read_error(error: AtomicJsonError) -> RedisCliError:
    if error.reason is AtomicJsonErrorReason.LOCKED:
        return RedisCliError(ErrorCode.PROFILE_REGISTRY, "profile registry is locked", retryable=True)
    return RedisCliError(ErrorCode.PROFILE_REGISTRY, "profile registry is unreadable or invalid")


def _write_error(error: AtomicJsonError) -> RedisCliError:
    if error.reason is AtomicJsonErrorReason.LOCKED:
        return RedisCliError(ErrorCode.PROFILE_REGISTRY, "profile registry is locked", retryable=True)
    return RedisCliError(ErrorCode.PROFILE_REGISTRY, "profile registry could not be written")


def _registry_to_document(registry: ProfileRegistry) -> RegistryDocument:
    profiles: list[ProfileDocument] = [
        ProfileDocument(
            name=record.name.value,
            settings=SettingsDocument(
                host=record.settings.host,
                port=record.settings.port,
                username=record.settings.username,
                database=record.settings.database,
                connection_timeout=record.settings.connection_timeout,
                tls=record.settings.tls,
            ),
            description=record.description,
            password_present=record.password_present,
        )
        for record in registry.profiles
    ]
    bindings: list[BindingDocument] = [
        BindingDocument(path=str(item.path), profile=item.profile.value) for item in registry.bindings
    ]
    return RegistryDocument(
        schema=JsonProfileStore.SCHEMA,
        version=JsonProfileStore.VERSION,
        profiles=profiles,
        bindings=bindings,
    )


def _registry_from_document(document: JsonObject) -> ProfileRegistry:
    if document.get("schema") != JsonProfileStore.SCHEMA or document.get("version") != JsonProfileStore.VERSION:
        raise RedisCliError(ErrorCode.PROFILE_REGISTRY, "profile registry schema is unsupported")
    profiles_value = document.get("profiles")
    bindings_value = document.get("bindings")
    if not isinstance(profiles_value, list) or not isinstance(bindings_value, list):
        raise RedisCliError(ErrorCode.PROFILE_REGISTRY, "profile registry schema is invalid")
    profiles = tuple(_profile_from_json(item) for item in profiles_value)
    bindings = tuple(_binding_from_json(item) for item in bindings_value)
    try:
        return ProfileRegistry(profiles=profiles, bindings=bindings)
    except ValueError as exc:
        raise RedisCliError(ErrorCode.PROFILE_REGISTRY, "profile registry schema is invalid") from exc


def _profile_from_json(value: JsonValue) -> ProfileRecord:
    if not is_json_object(value):
        raise RedisCliError(ErrorCode.PROFILE_REGISTRY, "profile record is invalid")
    document = value
    settings = document.get("settings")
    if not is_json_object(settings):
        raise RedisCliError(ErrorCode.PROFILE_REGISTRY, "profile settings are invalid")
    try:
        record = ProfileRecord(
            name=ProfileName(value=_required_string(document, "name")),
            settings=RedisSettings(
                host=_required_string(settings, "host"),
                port=_required_int(settings, "port"),
                username=_required_string(settings, "username"),
                database=_required_int(settings, "database"),
                connection_timeout=_required_number(settings, "connection_timeout"),
                tls=_required_bool(settings, "tls"),
            ),
            description=_optional_string(document, "description"),
            password_present=_required_bool(document, "password_present"),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise RedisCliError(ErrorCode.PROFILE_REGISTRY, "profile record is invalid") from exc
    return record


def _binding_from_json(value: JsonValue) -> DirectoryBinding:
    if not is_json_object(value):
        raise RedisCliError(ErrorCode.PROFILE_REGISTRY, "directory binding is invalid")
    document = value
    try:
        return DirectoryBinding(
            path=Path(_required_string(document, "path")),
            profile=ProfileName(value=_required_string(document, "profile")),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise RedisCliError(ErrorCode.PROFILE_REGISTRY, "directory binding is invalid") from exc


def _required_string(value: JsonObject, key: str) -> str:
    item = value[key]
    if not isinstance(item, str):
        raise TypeError(key)
    return item


def _optional_string(value: JsonObject, key: str) -> str | None:
    item = value.get(key)
    if item is not None and not isinstance(item, str):
        raise TypeError(key)
    return item


def _required_int(value: JsonObject, key: str) -> int:
    item = value[key]
    if isinstance(item, bool) or not isinstance(item, int):
        raise TypeError(key)
    return item


def _required_number(value: JsonObject, key: str) -> float:
    item = value[key]
    if isinstance(item, bool) or not isinstance(item, (int, float)):
        raise TypeError(key)
    return float(item)


def _required_bool(value: JsonObject, key: str) -> bool:
    item = value[key]
    if not isinstance(item, bool):
        raise TypeError(key)
    return item


__all__ = ["JsonProfileStore"]
