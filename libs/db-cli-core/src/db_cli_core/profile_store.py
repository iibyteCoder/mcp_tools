"""Concurrent-safe persistence for connection profiles and directory bindings."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from filelock import FileLock
from platformdirs import user_config_path

from db_cli_core.enums import ConnectionField, DatabaseKind, ProfileStorage, RegistryField, RegistryVersion
from db_cli_core.errors import ProfileNotFoundError
from db_cli_core.profile_models import ConnectionProfile, ConnectionSettings
from db_cli_core.secrets import SecretStore, SystemSecretStore


class ProfileStore:
    """Own the registry format; callers never read or write the file directly."""

    def __init__(self, path: Path | None = None, secret_store: SecretStore | None = None) -> None:
        self.path = (
            path
            or user_config_path(ProfileStorage.APPLICATION.value, appauthor=False, roaming=True)
            / ProfileStorage.FILE_NAME.value
        )
        self._lock = FileLock(f"{self.path}{ProfileStorage.LOCK_SUFFIX.value}")
        self._secret_store = secret_store or SystemSecretStore()

    def profiles(self, database_kind: DatabaseKind) -> list[ConnectionProfile]:
        document = self._read()
        raw_profiles = self._kind_mapping(document, RegistryField.PROFILES, database_kind)
        return [self._to_profile(database_kind, name, value) for name, value in sorted(raw_profiles.items())]

    def profile(self, database_kind: DatabaseKind, name: str) -> ConnectionProfile | None:
        document = self._read()
        raw = self._kind_mapping(document, RegistryField.PROFILES, database_kind).get(name)
        return self._to_profile(database_kind, name, raw) if isinstance(raw, dict) else None

    def save(self, profile: ConnectionProfile) -> None:
        with self._lock:
            document = self._read_unlocked()
            self._save_profile_unlocked(document, profile)
            self._write_unlocked(document)

    def rename(self, database_kind: DatabaseKind, name: str, new_name: str) -> None:
        """Move the profile, its credential, and all bindings without overwriting another name."""
        with self._lock:
            document = self._read_unlocked()
            profiles = self._kind_mapping(document, RegistryField.PROFILES, database_kind)
            if name not in profiles:
                raise ProfileNotFoundError(f"连接配置不存在: {name}")
            if new_name in profiles:
                raise ValueError(f"连接配置已存在: {new_name}")
            original = self._to_profile(database_kind, name, profiles[name])
            self._save_profile_unlocked(document, ConnectionProfile(new_name, database_kind, original.settings))
            del profiles[name]
            bindings = self._kind_mapping(document, RegistryField.BINDINGS, database_kind)
            for directory, bound_name in bindings.items():
                if bound_name == name:
                    bindings[directory] = new_name
            self._write_unlocked(document)
            self._secret_store.delete(database_kind, name)

    def save_and_bind(self, profile: ConnectionProfile, directory: Path) -> None:
        with self._lock:
            document = self._read_unlocked()
            self._save_profile_unlocked(document, profile)
            bindings = self._kind_mapping(document, RegistryField.BINDINGS, profile.database_kind)
            bindings[self._path_key(directory)] = profile.name
            self._write_unlocked(document)

    def remove(self, database_kind: DatabaseKind, name: str) -> bool:
        with self._lock:
            document = self._read_unlocked()
            profiles = self._kind_mapping(document, RegistryField.PROFILES, database_kind)
            removed = profiles.pop(name, None) is not None
            bindings = self._kind_mapping(document, RegistryField.BINDINGS, database_kind)
            stale_paths = [path for path, profile_name in bindings.items() if profile_name == name]
            for path in stale_paths:
                del bindings[path]
            if removed or stale_paths:
                self._write_unlocked(document)
                self._secret_store.delete(database_kind, name)
            return removed

    def bind_existing(self, database_kind: DatabaseKind, directory: Path, profile_name: str) -> ConnectionProfile:
        with self._lock:
            document = self._read_unlocked()
            raw_profile = self._kind_mapping(document, RegistryField.PROFILES, database_kind).get(profile_name)
            if not isinstance(raw_profile, dict):
                raise ProfileNotFoundError(f"连接配置不存在: {profile_name}")
            bindings = self._kind_mapping(document, RegistryField.BINDINGS, database_kind)
            bindings[self._path_key(directory)] = profile_name
            self._write_unlocked(document)
            return self._to_profile(database_kind, profile_name, raw_profile)

    def unbind(self, database_kind: DatabaseKind, directory: Path) -> bool:
        with self._lock:
            document = self._read_unlocked()
            bindings = self._kind_mapping(document, RegistryField.BINDINGS, database_kind)
            removed = bindings.pop(self._path_key(directory), None) is not None
            if removed:
                self._write_unlocked(document)
            return removed

    def nearest_binding(self, database_kind: DatabaseKind, directory: Path) -> tuple[Path, str] | None:
        document = self._read()
        bindings = self._kind_mapping(document, RegistryField.BINDINGS, database_kind)
        resolved = directory.resolve()
        for candidate in (resolved, *resolved.parents):
            profile_name = bindings.get(self._path_key(candidate))
            if isinstance(profile_name, str):
                return candidate, profile_name
        return None

    def _read(self) -> dict[str, Any]:
        with self._lock:
            return self._read_unlocked()

    def _read_unlocked(self) -> dict[str, Any]:
        if not self.path.exists():
            return self._empty_document()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"连接配置文件无法读取: {self.path}: {exc}") from exc
        if not isinstance(data, dict) or data.get(RegistryField.VERSION.value) != RegistryVersion.CURRENT:
            raise ValueError(f"不支持的连接配置文件版本: {self.path}")
        return data

    def _write_unlocked(self, document: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        file_descriptor, temporary_name = tempfile.mkstemp(
            prefix=ProfileStorage.TEMPORARY_PREFIX.value,
            suffix=ProfileStorage.TEMPORARY_SUFFIX.value,
            dir=self.path.parent,
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(file_descriptor, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(document, stream, ensure_ascii=False, indent=2, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, self.path)
        finally:
            temporary_path.unlink(missing_ok=True)

    @staticmethod
    def _empty_document() -> dict[str, Any]:
        return {
            RegistryField.VERSION.value: RegistryVersion.CURRENT,
            RegistryField.PROFILES.value: {kind.value: {} for kind in DatabaseKind},
            RegistryField.BINDINGS.value: {kind.value: {} for kind in DatabaseKind},
        }

    @staticmethod
    def _kind_mapping(document: dict[str, Any], field: RegistryField, database_kind: DatabaseKind) -> dict[str, Any]:
        section = document.setdefault(field.value, {})
        if not isinstance(section, dict):
            raise ValueError(f"连接配置字段 {field.value} 格式错误")
        mapping = section.setdefault(database_kind.value, {})
        if not isinstance(mapping, dict):
            raise ValueError(f"连接配置字段 {field.value}.{database_kind.value} 格式错误")
        return mapping

    def _to_profile(self, database_kind: DatabaseKind, name: str, value: Any) -> ConnectionProfile:
        if not isinstance(value, dict):
            raise ValueError(f"连接配置 {database_kind.value}/{name} 格式错误")
        raw_settings = value.get(RegistryField.SETTINGS.value)
        if not isinstance(raw_settings, dict):
            raise ValueError(f"连接配置 {database_kind.value}/{name} 缺少 settings")
        settings: ConnectionSettings = {}
        for key, item in raw_settings.items():
            if not isinstance(key, str) or not isinstance(item, (str, int, float, bool, type(None))):
                raise ValueError(f"连接配置 {database_kind.value}/{name} 包含不支持的值")
            settings[key] = item
        if value.get(RegistryField.CREDENTIAL.value) is True:
            password = self._secret_store.get(database_kind, name)
            if password is None:
                raise ValueError(f"连接配置 {database_kind.value}/{name} 的系统凭据不存在")
            settings[ConnectionField.PASSWORD.value] = password
        return ConnectionProfile(name, database_kind, settings)

    def _save_profile_unlocked(self, document: dict[str, Any], profile: ConnectionProfile) -> None:
        settings = dict(profile.settings)
        password = settings.pop(ConnectionField.PASSWORD.value, None)
        has_credential = isinstance(password, str) and bool(password)
        if isinstance(password, str) and password:
            self._secret_store.set(profile.database_kind, profile.name, password)
        else:
            self._secret_store.delete(profile.database_kind, profile.name)
        profiles = self._kind_mapping(document, RegistryField.PROFILES, profile.database_kind)
        profiles[profile.name] = {
            RegistryField.SETTINGS.value: settings,
            RegistryField.CREDENTIAL.value: has_credential,
        }

    @staticmethod
    def _path_key(directory: Path) -> str:
        return os.path.normcase(str(directory.resolve()))
