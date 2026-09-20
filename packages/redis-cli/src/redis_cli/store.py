"""Locked, atomic persistence for Redis profile metadata."""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, cast

from filelock import FileLock, Timeout
from platformdirs import user_config_path

from redis_cli.constants import PROFILE_REGISTRY_DIRECTORY, PROFILE_REGISTRY_FILE_NAME, PROFILE_REGISTRY_VERSION
from redis_cli.domain import (
    DirectoryBinding,
    ProfileName,
    ProfileRecord,
    ProfileRegistry,
    RedisSettings,
)
from redis_cli.enums import RegistrySchema
from redis_cli.json_types import BindingDocument, ProfileDocument, RegistryDocument, SettingsDocument

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator


class ProfileStoreError(RuntimeError):
    """Raised when profile metadata cannot be read or written."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class JsonProfileStore:
    """Persist profiles under ``%APPDATA%/db-cli/connections.json``."""

    SCHEMA = RegistrySchema.REDIS_CONNECTIONS.value
    VERSION = PROFILE_REGISTRY_VERSION
    LOCK_TIMEOUT_SECONDS = 1.0

    def __init__(self, path: Path | None = None, *, lock_timeout: float = 0.0) -> None:
        self.path = path or (user_config_path(PROFILE_REGISTRY_DIRECTORY) / PROFILE_REGISTRY_FILE_NAME)
        self.lock_path = Path(f"{self.path}.lock")
        self.lock_timeout = lock_timeout

    def read(self) -> ProfileRegistry:
        with self._locked():
            return self._read_unlocked()

    def update(self, updater: Callable[[ProfileRegistry], ProfileRegistry]) -> ProfileRegistry:
        with self._locked():
            registry = updater(self._read_unlocked())
            self._write_unlocked(registry)
            return registry

    @contextmanager
    def _locked(self) -> Iterator[None]:
        lock = FileLock(str(self.lock_path), timeout=self.lock_timeout)
        try:
            lock.acquire()
        except Timeout as exc:
            raise ProfileStoreError("profile registry is locked") from exc
        try:
            yield
        finally:
            lock.release()

    def _read_unlocked(self) -> ProfileRegistry:
        if not self.path.exists():
            return ProfileRegistry()
        try:
            document = json.loads(self.path.read_text(encoding="utf-8"))
            return _registry_from_json(document)
        except ProfileStoreError:
            raise
        except (OSError, UnicodeError, ValueError, TypeError, KeyError) as exc:
            raise ProfileStoreError("profile registry is unreadable or invalid") from exc

    def _write_unlocked(self, registry: ProfileRegistry) -> None:
        document: RegistryDocument = {
            "schema": self.SCHEMA,
            "version": self.VERSION,
            "profiles": [
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
            ],
            "bindings": [
                BindingDocument(path=str(item.path), profile=item.profile.value) for item in registry.bindings
            ],
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary_name = tempfile.mkstemp(prefix=".connections.", suffix=".tmp", dir=self.path.parent)
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
            raise ProfileStoreError("profile registry could not be written") from exc


def _registry_from_json(value: object) -> ProfileRegistry:
    if not isinstance(value, dict):
        raise ProfileStoreError("profile registry schema is invalid")
    document = cast("dict[str, object]", value)
    if document.get("schema") != JsonProfileStore.SCHEMA or document.get("version") != JsonProfileStore.VERSION:
        raise ProfileStoreError("profile registry schema is unsupported")
    profiles_value = document.get("profiles")
    bindings_value = document.get("bindings")
    if not isinstance(profiles_value, list) or not isinstance(bindings_value, list):
        raise ProfileStoreError("profile registry schema is invalid")
    profiles = tuple(_profile_from_json(item) for item in profiles_value)
    bindings = tuple(_binding_from_json(item) for item in bindings_value)
    try:
        return ProfileRegistry(profiles=profiles, bindings=bindings)
    except ValueError as exc:
        raise ProfileStoreError("profile registry schema is invalid") from exc


def _profile_from_json(value: object) -> ProfileRecord:
    if not isinstance(value, dict):
        raise ProfileStoreError("profile record is invalid")
    document = cast("dict[str, object]", value)
    settings = document.get("settings")
    if not isinstance(settings, dict):
        raise ProfileStoreError("profile settings are invalid")
    try:
        record = ProfileRecord(
            name=ProfileName(_required_string(document, "name")),
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
        raise ProfileStoreError("profile record is invalid") from exc
    return record


def _binding_from_json(value: object) -> DirectoryBinding:
    if not isinstance(value, dict):
        raise ProfileStoreError("directory binding is invalid")
    document = cast("dict[str, object]", value)
    try:
        return DirectoryBinding(
            path=Path(_required_string(document, "path")),
            profile=ProfileName(_required_string(document, "profile")),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ProfileStoreError("directory binding is invalid") from exc


def _required_string(value: dict[str, object], key: str) -> str:
    item = value[key]
    if not isinstance(item, str):
        raise TypeError(key)
    return item


def _optional_string(value: dict[str, object], key: str) -> str | None:
    item = value.get(key)
    if item is not None and not isinstance(item, str):
        raise TypeError(key)
    return item


def _required_int(value: dict[str, object], key: str) -> int:
    item = value[key]
    if isinstance(item, bool) or not isinstance(item, int):
        raise TypeError(key)
    return item


def _required_number(value: dict[str, object], key: str) -> float:
    item = value[key]
    if isinstance(item, bool) or not isinstance(item, (int, float)):
        raise TypeError(key)
    return float(item)


def _required_bool(value: dict[str, object], key: str) -> bool:
    item = value[key]
    if not isinstance(item, bool):
        raise TypeError(key)
    return item


__all__ = ["JsonProfileStore", "ProfileStoreError"]
