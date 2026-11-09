"""Versioned, atomic and locked persistence for the profile registry.

Document I/O and locking are delegated to :class:`db_cli_kit.atomic_json.AtomicJsonStore`.
Unreadable registry I/O surfaces as :attr:`RegistryErrorCode.IO` (public
``input_error``/``file_read_error``) rather than being folded into
``profile_registry_corrupt``, following the shared kit's error taxonomy.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import TYPE_CHECKING, Final

from platformdirs import user_config_path

from db_cli_kit.atomic_json import AtomicJsonError, AtomicJsonErrorReason, AtomicJsonStore
from db_cli_kit.json_codec import JsonObject, JsonValue, is_json_object
from db_cli_kit.profiles import DirectoryBinding, ProfileName
from mysql_cli.domain.profile import (
    ProfileRecord,
    ProfileRegistry,
    ProfileSettings,
    RegistryErrorCode,
)
from mysql_cli.ports.profile_store import ProfileStore, ProfileStoreError

if TYPE_CHECKING:
    from collections.abc import Callable

TOP_LEVEL_KEYS: Final[frozenset[str]] = frozenset({"schema", "version", "profiles", "bindings"})
PROFILE_KEYS: Final[tuple[frozenset[str], ...]] = (
    frozenset({"name", "settings", "password_present"}),
    frozenset({"name", "settings", "description", "password_present"}),
)
SETTINGS_KEYS: Final[frozenset[str]] = frozenset(
    {"host", "port", "user", "database", "charset", "connect_timeout", "read_timeout"}
)
BINDING_KEYS: Final[frozenset[str]] = frozenset({"path", "profile"})

_ERROR_CODE_BY_REASON: Final[dict[AtomicJsonErrorReason, RegistryErrorCode]] = {
    AtomicJsonErrorReason.CORRUPT: RegistryErrorCode.CORRUPT,
    AtomicJsonErrorReason.LOCKED: RegistryErrorCode.LOCKED,
    AtomicJsonErrorReason.IO: RegistryErrorCode.IO,
}

_ERROR_MESSAGE_BY_REASON: Final[dict[AtomicJsonErrorReason, str]] = {
    AtomicJsonErrorReason.CORRUPT: "profile registry is unreadable",
    AtomicJsonErrorReason.LOCKED: "profile registry is locked",
    AtomicJsonErrorReason.IO: "profile registry could not be written",
}


class JsonProfileStore:
    """Persist one explicit JSON schema under a process-safe lock."""

    SCHEMA: Final[str] = "db-mysql.profile-registry"
    VERSION: Final[int] = 1
    CLI_LOCK_TIMEOUT_SECONDS: Final[float] = 1.0

    def __init__(
        self,
        path: Path | None = None,
        *,
        lock_timeout: float = 0.0,
    ) -> None:
        self.path = path or (user_config_path("db-mysql") / "profiles.json")
        self._store = AtomicJsonStore(self.path, lock_timeout)

    @property
    def lock_path(self) -> Path:
        """Path of the process-safe lock file guarding the registry."""

        return self._store.lock_path

    def read(self) -> ProfileRegistry:
        try:
            document = self._store.read()
        except AtomicJsonError as exc:
            raise _translate(exc, io_message="profile registry is unreadable") from exc
        return ProfileRegistry() if document is None else _registry_from_document(document)

    def write(self, registry: ProfileRegistry) -> None:
        document = _registry_to_document(registry)
        try:
            self._store.write(document)
        except AtomicJsonError as exc:
            raise _translate(exc) from exc

    def update(self, updater: Callable[[ProfileRegistry], ProfileRegistry]) -> ProfileRegistry:
        def apply(document: JsonObject | None) -> JsonObject:
            current = ProfileRegistry() if document is None else _registry_from_document(document)
            return _registry_to_document(updater(current))

        try:
            document = self._store.update(apply)
        except AtomicJsonError as exc:
            raise _translate(exc) from exc
        return _registry_from_document(document)


def _translate(error: AtomicJsonError, *, io_message: str | None = None) -> ProfileStoreError:
    """Map a shared persistence failure to the stable MySQL registry error."""

    message = _ERROR_MESSAGE_BY_REASON[error.reason]
    if error.reason is AtomicJsonErrorReason.IO and io_message is not None:
        message = io_message
    return ProfileStoreError(_ERROR_CODE_BY_REASON[error.reason], message)


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
                    "database": record.settings.database,
                    "charset": record.settings.charset,
                    "connect_timeout": record.settings.connect_timeout,
                    "read_timeout": record.settings.read_timeout,
                },
                "description": record.description,
                "password_present": record.password_present,
            }
        )
    bindings: list[JsonValue] = [
        {"path": str(binding.path), "profile": binding.profile.value} for binding in registry.bindings
    ]
    return {
        "schema": JsonProfileStore.SCHEMA,
        "version": JsonProfileStore.VERSION,
        "profiles": profiles,
        "bindings": bindings,
    }


def _registry_from_document(document: JsonObject) -> ProfileRegistry:
    if set(document) != TOP_LEVEL_KEYS:
        raise ProfileStoreError(RegistryErrorCode.CORRUPT, "profile registry schema is invalid")
    if document.get("schema") != JsonProfileStore.SCHEMA:
        raise ProfileStoreError(RegistryErrorCode.CORRUPT, "profile registry schema is invalid")
    if document.get("version") != JsonProfileStore.VERSION:
        raise ProfileStoreError(RegistryErrorCode.UNSUPPORTED_VERSION, "profile registry version is unsupported")
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
    if not is_json_object(value):
        raise ProfileStoreError(RegistryErrorCode.CORRUPT, "profile record is invalid")
    if set(value) not in PROFILE_KEYS:
        raise ProfileStoreError(RegistryErrorCode.CORRUPT, "profile record is invalid")
    name = _string(value, "name")
    settings_value = value.get("settings")
    if not is_json_object(settings_value):
        raise ProfileStoreError(RegistryErrorCode.CORRUPT, "profile settings are invalid")
    if set(settings_value) != SETTINGS_KEYS:
        raise ProfileStoreError(RegistryErrorCode.CORRUPT, "profile settings are invalid")
    settings = ProfileSettings(
        host=_string(settings_value, "host"),
        port=_int(settings_value, "port"),
        user=_string(settings_value, "user"),
        database=_optional_string(settings_value, "database"),
        charset=_string(settings_value, "charset"),
        connect_timeout=_number(settings_value, "connect_timeout"),
        read_timeout=_number(settings_value, "read_timeout"),
    )
    password_present = value.get("password_present")
    if not isinstance(password_present, bool):
        raise ProfileStoreError(RegistryErrorCode.CORRUPT, "profile password metadata is invalid")
    return ProfileRecord(
        name=ProfileName(value=name),
        settings=settings,
        description=_optional_string(value, "description"),
        password_present=password_present,
    )


def _binding_from_document(value: JsonValue) -> DirectoryBinding:
    if not is_json_object(value):
        raise ProfileStoreError(RegistryErrorCode.CORRUPT, "directory binding is invalid")
    if set(value) != BINDING_KEYS:
        raise ProfileStoreError(RegistryErrorCode.CORRUPT, "directory binding is invalid")
    return DirectoryBinding(path=Path(_string(value, "path")), profile=ProfileName(value=_string(value, "profile")))


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


__all__ = ["JsonProfileStore", "ProfileStore", "ProfileStoreError"]
