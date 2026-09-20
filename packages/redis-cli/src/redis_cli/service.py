"""Profile CRUD, directory selection and connection resolution."""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import unquote, urlparse

from redis_cli.constants import (
    DEFAULT_CONNECTION_TIMEOUT_SECONDS,
    DEFAULT_REDIS_DATABASE,
    DEFAULT_REDIS_HOST,
    DEFAULT_REDIS_PORT,
)
from redis_cli.domain import (
    ConnectionOverrides,
    DirectoryBinding,
    ParsedRedisUrl,
    ProfileName,
    ProfileRecord,
    ProfileRegistry,
    ProfileSelection,
    ProfileSetRequest,
    RedisConnectionConfig,
    RedisSettings,
    ResolvedConnection,
    normalize_directory,
    replace_profile_name,
)
from redis_cli.enums import ErrorCode, ProfileSelectionSource, RedisUrlScheme
from redis_cli.secrets import SecretStore, SecretStoreError

if TYPE_CHECKING:
    from redis_cli.store import JsonProfileStore


class ProfileServiceError(RuntimeError):
    """Expected profile or configuration failure."""

    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ProfileService:
    """Coordinate profile metadata, credentials and active-directory bindings."""

    def __init__(
        self,
        store: JsonProfileStore,
        secret_store: SecretStore,
        *,
        working_directory: Path | None = None,
    ) -> None:
        self.store = store
        self.secret_store = secret_store
        self.working_directory = normalize_directory(working_directory or Path.cwd())

    def list_profiles(self) -> tuple[ProfileRecord, ...]:
        return self.store.read().profiles

    def require(self, name: ProfileName) -> ProfileRecord:
        profile = self.store.read().find(name)
        if profile is None:
            raise ProfileServiceError(ErrorCode.PROFILE_NOT_FOUND, "profile not found")
        return profile

    def current(self, directory: Path | None = None) -> ProfileSelection | None:
        registry = self.store.read()
        binding = registry.binding_for(directory or self.working_directory)
        if binding is None:
            return None
        profile = registry.find(binding.profile)
        if profile is None:
            raise ProfileServiceError(
                ErrorCode.PROFILE_NOT_FOUND,
                "directory binding points to a missing profile",
            )
        return ProfileSelection(profile=profile, source=ProfileSelectionSource.DIRECTORY, binding=binding)

    def set(self, request: ProfileSetRequest) -> ProfileRecord:
        registry = self.store.read()
        existing = registry.find(request.name)
        settings, description, password_present = self._settings_for_request(request, existing)

        if request.password is not None:
            if not request.password:
                raise ProfileServiceError(ErrorCode.INVALID_ARGUMENT, "password cannot be empty")
            self._set_password(request.name, request.password)
            password_present = True
        elif request.clear_password:
            self._delete_password(request.name)
            password_present = False

        record = ProfileRecord(
            name=request.name,
            settings=settings,
            description=description,
            password_present=password_present,
        )

        def update(current: ProfileRegistry) -> ProfileRegistry:
            profiles = tuple(item for item in current.profiles if item.name != request.name)
            bindings = current.bindings
            if request.bind:
                binding = DirectoryBinding(path=self.working_directory, profile=request.name)
                bindings = (*tuple(item for item in bindings if item.path != binding.path), binding)
            return ProfileRegistry(profiles=(*profiles, record), bindings=bindings)

        self.store.update(update)
        return record

    def bind(self, name: ProfileName, directory: Path | None = None) -> DirectoryBinding:
        self.require(name)
        binding = DirectoryBinding(path=directory or self.working_directory, profile=name)

        def update(registry: ProfileRegistry) -> ProfileRegistry:
            bindings = (*tuple(item for item in registry.bindings if item.path != binding.path), binding)
            return ProfileRegistry(profiles=registry.profiles, bindings=bindings)

        self.store.update(update)
        return binding

    def clear(self, directory: Path | None = None) -> DirectoryBinding | None:
        path = normalize_directory(directory or self.working_directory)
        removed: list[DirectoryBinding] = []

        def update(registry: ProfileRegistry) -> ProfileRegistry:
            removed.extend(item for item in registry.bindings if item.path == path)
            return ProfileRegistry(
                profiles=registry.profiles,
                bindings=tuple(item for item in registry.bindings if item.path != path),
            )

        self.store.update(update)
        return removed[0] if removed else None

    def rename(self, old: ProfileName, new: ProfileName) -> ProfileRecord:
        registry = self.store.read()
        original = registry.find(old)
        if original is None:
            raise ProfileServiceError(ErrorCode.PROFILE_NOT_FOUND, "profile not found")
        if registry.find(new) is not None:
            raise ProfileServiceError(ErrorCode.PROFILE_CONFLICT, "profile already exists")
        password = self._get_password(old) if original.password_present else None
        if password is not None:
            self._set_password(new, password)
        renamed = replace_profile_name(original, new)

        def update(current: ProfileRegistry) -> ProfileRegistry:
            profiles = tuple(renamed if item.name == old else item for item in current.profiles)
            bindings = tuple(replace(item, profile=new) if item.profile == old else item for item in current.bindings)
            return ProfileRegistry(profiles=profiles, bindings=bindings)

        try:
            self.store.update(update)
        except Exception:
            if password is not None:
                self._delete_password(new)
            raise
        if password is not None:
            self._delete_password(old)
        return renamed

    def remove(self, name: ProfileName) -> int:
        registry = self.store.read()
        if registry.find(name) is None:
            raise ProfileServiceError(ErrorCode.PROFILE_NOT_FOUND, "profile not found")
        removed_bindings = sum(item.profile == name for item in registry.bindings)
        self.store.update(
            lambda current: ProfileRegistry(
                profiles=tuple(item for item in current.profiles if item.name != name),
                bindings=tuple(item for item in current.bindings if item.profile != name),
            )
        )
        self._delete_password(name)
        return removed_bindings

    def resolve(self, explicit_profile: ProfileName | None, overrides: ConnectionOverrides) -> ResolvedConnection:
        """Resolve defaults, directory selection, explicit profile and overrides."""

        selected: ProfileRecord | None
        source = ProfileSelectionSource.DEFAULTS
        if explicit_profile is not None:
            selected = self.require(explicit_profile)
            source = ProfileSelectionSource.EXPLICIT
        else:
            current = self.current()
            selected = None if current is None else current.profile
            if selected is not None:
                source = ProfileSelectionSource.DIRECTORY

        settings = selected.settings if selected is not None else _environment_settings()
        password = self._get_password(selected.name) if selected is not None and selected.password_present else ""
        tls = settings.tls

        if overrides.url is not None:
            parsed = parse_redis_url(overrides.url)
            settings = parsed.settings
            password = parsed.password
            tls = parsed.tls
        settings = RedisSettings(
            host=settings.host if overrides.host is None else overrides.host,
            port=settings.port if overrides.port is None else overrides.port,
            username=settings.username if overrides.username is None else overrides.username,
            database=settings.database if overrides.database is None else overrides.database,
            connection_timeout=(
                settings.connection_timeout if overrides.connection_timeout is None else overrides.connection_timeout
            ),
            tls=settings.tls,
        )
        if overrides.password is not None:
            password = overrides.password
        return ResolvedConnection(
            config=RedisConnectionConfig.from_settings(settings, password=password, tls=tls),
            profile=selected.name if selected is not None else None,
            source=source,
        )

    def _settings_for_request(
        self,
        request: ProfileSetRequest,
        existing: ProfileRecord | None,
    ) -> tuple[RedisSettings, str | None, bool]:
        try:
            if existing is None:
                if request.settings.host is None:
                    raise ProfileServiceError(ErrorCode.INVALID_ARGUMENT, "new profile requires --host or --url")
                settings = RedisSettings(
                    host=request.settings.host,
                    port=DEFAULT_REDIS_PORT if request.settings.port is None else request.settings.port,
                    username="" if request.settings.username is None else request.settings.username,
                    database=DEFAULT_REDIS_DATABASE if request.settings.database is None else request.settings.database,
                    connection_timeout=(
                        DEFAULT_CONNECTION_TIMEOUT_SECONDS
                        if request.settings.connection_timeout is None
                        else request.settings.connection_timeout
                    ),
                    tls=False if request.settings.tls is None else request.settings.tls,
                )
                return settings, request.description, False
            settings = request.settings.apply(existing.settings)
            description = existing.description
            if request.description is not None:
                description = request.description
            if request.clear_description:
                description = None
            return settings, description, existing.password_present
        except ValueError as exc:
            raise ProfileServiceError(ErrorCode.INVALID_ARGUMENT, "profile settings are invalid") from exc

    def _get_password(self, name: ProfileName) -> str:
        try:
            password = self.secret_store.get(name)
        except SecretStoreError as exc:
            raise ProfileServiceError(ErrorCode.SECRET_STORE, "secret store operation failed") from exc
        if password is None:
            raise ProfileServiceError(ErrorCode.AUTH_FAILED, "profile password is missing")
        return password

    def _set_password(self, name: ProfileName, password: str) -> None:
        try:
            self.secret_store.set(name, password)
        except SecretStoreError as exc:
            raise ProfileServiceError(ErrorCode.SECRET_STORE, "secret store operation failed") from exc

    def _delete_password(self, name: ProfileName) -> None:
        try:
            self.secret_store.delete(name)
        except SecretStoreError as exc:
            raise ProfileServiceError(ErrorCode.SECRET_STORE, "secret store operation failed") from exc


def _environment_settings() -> RedisSettings:
    try:
        return RedisSettings(
            host=os.environ.get("REDIS_HOST", DEFAULT_REDIS_HOST),
            port=int(os.environ.get("REDIS_PORT", str(DEFAULT_REDIS_PORT))),
            username=os.environ.get("REDIS_USERNAME", ""),
            database=int(os.environ.get("REDIS_DB", str(DEFAULT_REDIS_DATABASE))),
            connection_timeout=float(
                os.environ.get("REDIS_CONNECTION_TIMEOUT", str(DEFAULT_CONNECTION_TIMEOUT_SECONDS))
            ),
        )
    except (TypeError, ValueError) as exc:
        raise ProfileServiceError(ErrorCode.INVALID_ARGUMENT, "REDIS_* environment settings are invalid") from exc


def parse_redis_url(value: str) -> ParsedRedisUrl:
    """Parse a Redis URL without exposing credentials."""

    parsed = urlparse(value)
    try:
        scheme = RedisUrlScheme(parsed.scheme)
    except ValueError as exc:
        raise ProfileServiceError(ErrorCode.INVALID_ARGUMENT, "url must use redis:// or rediss://") from exc
    if not parsed.hostname:
        raise ProfileServiceError(ErrorCode.INVALID_ARGUMENT, "url must include a Redis host")
    try:
        settings = RedisSettings(
            host=parsed.hostname,
            port=parsed.port or DEFAULT_REDIS_PORT,
            username=unquote(parsed.username or ""),
            database=int(parsed.path.lstrip("/") or str(DEFAULT_REDIS_DATABASE)),
            connection_timeout=DEFAULT_CONNECTION_TIMEOUT_SECONDS,
            tls=scheme.tls,
        )
    except (TypeError, ValueError) as exc:
        raise ProfileServiceError(ErrorCode.INVALID_ARGUMENT, "url contains invalid Redis settings") from exc
    return ParsedRedisUrl(settings=settings, password=unquote(parsed.password or ""), tls=scheme.tls)


__all__ = ["ProfileService", "ProfileServiceError", "parse_redis_url"]
