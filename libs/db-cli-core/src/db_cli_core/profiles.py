"""Application service for named connections and directory bindings."""

from __future__ import annotations

from pathlib import Path

from db_cli_core.enums import ConnectionSource, DatabaseKind
from db_cli_core.errors import ProfileNotFoundError
from db_cli_core.profile_models import ConnectionProfile, ConnectionSelection, ConnectionSettings
from db_cli_core.profile_store import ProfileStore


class ConnectionProfileManager:
    def __init__(self, database_kind: DatabaseKind, store: ProfileStore | None = None) -> None:
        self.database_kind = database_kind
        self.store = store or ProfileStore()

    def set(
        self,
        name: str,
        settings: ConnectionSettings,
        directory: Path | None = None,
    ) -> ConnectionSelection:
        profile_name = self._validated_name(name)
        profile = ConnectionProfile(profile_name, self.database_kind, settings)
        if directory is not None:
            self.store.save_and_bind(profile, directory)
            return ConnectionSelection(profile, ConnectionSource.DIRECTORY, directory.resolve())
        self.store.save(profile)
        return ConnectionSelection(profile, ConnectionSource.PROFILE)

    def select(self, name: str, directory: Path) -> ConnectionSelection:
        profile_name = self._validated_name(name)
        profile = self.store.bind_existing(self.database_kind, directory, profile_name)
        return ConnectionSelection(profile, ConnectionSource.DIRECTORY, directory.resolve())

    def resolve(
        self,
        profile_name: str | None = None,
        directory: Path | None = None,
    ) -> ConnectionSelection | None:
        if profile_name is not None:
            return ConnectionSelection(self.require(profile_name), ConnectionSource.PROFILE)
        binding = self.store.nearest_binding(self.database_kind, directory or Path.cwd())
        if binding is None:
            return None
        bound_directory, name = binding
        profile = self.store.profile(self.database_kind, name)
        if profile is None:
            raise ProfileNotFoundError(f"目录绑定的连接配置不存在: {name}")
        return ConnectionSelection(profile, ConnectionSource.DIRECTORY, bound_directory)

    def require(self, name: str) -> ConnectionProfile:
        profile = self.find(name)
        if profile is None:
            raise ProfileNotFoundError(f"连接配置不存在: {name}")
        return profile

    def find(self, name: str) -> ConnectionProfile | None:
        return self.store.profile(self.database_kind, self._validated_name(name))

    def profiles(self) -> list[ConnectionProfile]:
        return self.store.profiles(self.database_kind)

    def remove(self, name: str) -> None:
        if not self.store.remove(self.database_kind, self._validated_name(name)):
            raise ProfileNotFoundError(f"连接配置不存在: {name}")

    def rename(self, name: str, new_name: str) -> None:
        self.store.rename(self.database_kind, self._validated_name(name), self._validated_name(new_name))

    def clear(self, directory: Path) -> None:
        if not self.store.unbind(self.database_kind, directory):
            raise ValueError(f"该目录没有直接绑定连接: {directory.resolve()}")

    @staticmethod
    def _validated_name(name: str) -> str:
        normalized = name.strip()
        if not normalized:
            raise ValueError("连接配置名称不能为空")
        return normalized
