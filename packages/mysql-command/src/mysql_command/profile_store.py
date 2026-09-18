"""Versioned, atomic and locked persistence for the profile registry."""

from __future__ import annotations

import json
import math
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

from filelock import FileLock, Timeout
from platformdirs import user_config_path

from mysql_command.json_codec import JsonValue, is_json_object
from mysql_command.profile_models import (
    DirectoryBinding,
    ProfileName,
    ProfileRecord,
    ProfileRegistry,
    ProfileSettings,
    RegistryErrorCode,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator


class ProfileStoreError(RuntimeError):
    """A stable, secret-free profile registry persistence error."""

    def __init__(self, code: RegistryErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ProfileStore(Protocol):
    """Typed store contract used by ``ProfileService`` and test fakes."""

    def read(self) -> ProfileRegistry: ...

    def write(self, registry: ProfileRegistry) -> None: ...

    def update(self, updater: Callable[[ProfileRegistry], ProfileRegistry]) -> ProfileRegistry: ...


class JsonProfileStore:
    """Persist one explicit JSON schema under a process-safe lock."""

    SCHEMA = "db-mysql.profile-registry"
    VERSION = 1

    def __init__(self, path: Path | None = None, *, lock_timeout: float = 0.0) -> None:
        self.path = path or (user_config_path("db-mysql") / "profiles.json")
        self.lock_path = Path(f"{self.path}.lock")
        self._lock_timeout = lock_timeout

    def read(self) -> ProfileRegistry:
        with self._locked():
            return self._read_unlocked()

    def write(self, registry: ProfileRegistry) -> None:
        with self._locked():
            self._write_unlocked(registry)

    def update(self, updater: Callable[[ProfileRegistry], ProfileRegistry]) -> ProfileRegistry:
        with self._locked():
            updated = updater(self._read_unlocked())
            self._write_unlocked(updated)
            return updated

    @contextmanager
    def _locked(self) -> Iterator[FileLock]:
        lock = FileLock(str(self.lock_path), timeout=self._lock_timeout)
        try:
            lock.acquire()
        except Timeout as exc:
            raise ProfileStoreError(RegistryErrorCode.LOCKED, "profile registry is locked") from exc
        try:
            yield lock
        finally:
            lock.release()

    def _read_unlocked(self) -> ProfileRegistry:
        if not self.path.exists():
            return ProfileRegistry()
        try:
            text = self.path.read_text(encoding="utf-8")
            loaded: object = json.loads(text)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ProfileStoreError(RegistryErrorCode.CORRUPT, "profile registry is unreadable") from exc
        try:
            return _registry_from_json(loaded)
        except ProfileStoreError:
            raise
        except (TypeError, ValueError, KeyError) as exc:
            raise ProfileStoreError(RegistryErrorCode.CORRUPT, "profile registry schema is invalid") from exc

    def _write_unlocked(self, registry: ProfileRegistry) -> None:
        document = _registry_to_json(registry)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary_name = tempfile.mkstemp(prefix=".profiles.", suffix=".tmp", dir=self.path.parent)
            temporary_path = Path(temporary_name)
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                    json.dump(document, stream, ensure_ascii=False, indent=2, sort_keys=True)
                    stream.write("\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary_path, self.path)
            finally:
                temporary_path.unlink(missing_ok=True)
        except OSError as exc:
            raise ProfileStoreError(RegistryErrorCode.IO, "profile registry could not be written") from exc


def _registry_to_json(registry: ProfileRegistry) -> dict[str, JsonValue]:
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


def _registry_from_json(value: object) -> ProfileRegistry:
    if not is_json_object(cast("JsonValue", value)):
        raise ProfileStoreError(RegistryErrorCode.CORRUPT, "profile registry must be a JSON object")
    document = cast("dict[str, JsonValue]", value)
    if set(document) != {"schema", "version", "profiles", "bindings"}:
        raise ProfileStoreError(RegistryErrorCode.CORRUPT, "profile registry schema is invalid")
    if document.get("schema") != JsonProfileStore.SCHEMA:
        raise ProfileStoreError(RegistryErrorCode.CORRUPT, "profile registry schema is invalid")
    if document.get("version") != JsonProfileStore.VERSION:
        raise ProfileStoreError(RegistryErrorCode.UNSUPPORTED_VERSION, "profile registry version is unsupported")
    profiles_value = document.get("profiles")
    bindings_value = document.get("bindings")
    if not isinstance(profiles_value, list) or not isinstance(bindings_value, list):
        raise ProfileStoreError(RegistryErrorCode.CORRUPT, "profile registry schema is invalid")
    profiles = tuple(_profile_from_json(item) for item in profiles_value)
    bindings = tuple(_binding_from_json(item) for item in bindings_value)
    return ProfileRegistry(profiles=profiles, bindings=bindings)


def _profile_from_json(value: JsonValue) -> ProfileRecord:
    if not is_json_object(value):
        raise ProfileStoreError(RegistryErrorCode.CORRUPT, "profile record is invalid")
    if set(value) != {"name", "settings", "password_present"}:
        raise ProfileStoreError(RegistryErrorCode.CORRUPT, "profile record is invalid")
    name = _string(value, "name")
    settings_value = value.get("settings")
    if not is_json_object(settings_value):
        raise ProfileStoreError(RegistryErrorCode.CORRUPT, "profile settings are invalid")
    if set(settings_value) != {
        "host",
        "port",
        "user",
        "database",
        "charset",
        "connect_timeout",
        "read_timeout",
    }:
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
    return ProfileRecord(name=ProfileName(value=name), settings=settings, password_present=password_present)


def _binding_from_json(value: JsonValue) -> DirectoryBinding:
    if not is_json_object(value):
        raise ProfileStoreError(RegistryErrorCode.CORRUPT, "directory binding is invalid")
    if set(value) != {"path", "profile"}:
        raise ProfileStoreError(RegistryErrorCode.CORRUPT, "directory binding is invalid")
    return DirectoryBinding(path=Path(_string(value, "path")), profile=ProfileName(value=_string(value, "profile")))


def _string(value: dict[str, JsonValue], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str):
        raise ProfileStoreError(RegistryErrorCode.CORRUPT, f"profile registry field {key} is invalid")
    return item


def _optional_string(value: dict[str, JsonValue], key: str) -> str | None:
    item = value.get(key)
    if item is None or isinstance(item, str):
        return item
    raise ProfileStoreError(RegistryErrorCode.CORRUPT, f"profile registry field {key} is invalid")


def _int(value: dict[str, JsonValue], key: str) -> int:
    item = value.get(key)
    if isinstance(item, bool) or not isinstance(item, int):
        raise ProfileStoreError(RegistryErrorCode.CORRUPT, f"profile registry field {key} is invalid")
    return item


def _number(value: dict[str, JsonValue], key: str) -> float:
    item = value.get(key)
    if isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(float(item)):
        raise ProfileStoreError(RegistryErrorCode.CORRUPT, f"profile registry field {key} is invalid")
    return float(item)


__all__ = ["JsonProfileStore", "ProfileStore", "ProfileStoreError"]
