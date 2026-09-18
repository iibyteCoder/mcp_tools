"""Application service for profile CRUD, bindings, credentials and validation."""

from __future__ import annotations

from dataclasses import replace
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from mysql_cli.profile_models import (
    DirectoryBinding,
    ProfileName,
    ProfileRecord,
    ProfileRegistry,
    ProfileSelection,
    ProfileSelectionSource,
    ProfileSetRequest,
    ProfileSettings,
    normalize_directory,
)
from mysql_cli.secret_store import KeyringSecretStore, SecretStoreError
from mysql_client import (
    DEFAULT_CONNECT_TIMEOUT_SECONDS,
    DEFAULT_MYSQL_CHARSET,
    DEFAULT_MYSQL_PORT,
    DEFAULT_READ_TIMEOUT_SECONDS,
    AiomysqlDriverFactory,
    ClientError,
    MySqlConnectionConfig,
    MySqlSession,
    SecretValue,
)

if TYPE_CHECKING:
    from mysql_cli.profile_store import ProfileStore
    from mysql_cli.secret_store import SecretStore


class ProfileServiceErrorCode(str, Enum):
    """Stable domain failures returned by the profile application service."""

    NOT_FOUND = "profile_not_found"
    CONFLICT = "profile_conflict"
    INVALID = "profile_invalid"
    SECRET_MISSING = "profile_secret_missing"
    SECRET_STORE = "secret_store_error"
    VALIDATION_FAILED = "profile_validation_failed"


class ProfileServiceError(RuntimeError):
    """Expected, secret-free profile operation failure."""

    def __init__(self, code: ProfileServiceErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ProfileValidator(Protocol):
    """Typed boundary for explicit connection validation."""

    async def validate(self, config: MySqlConnectionConfig) -> None: ...


class MySqlSessionValidator:
    """Validate a profile by opening and closing one real MySQL session."""

    async def validate(self, config: MySqlConnectionConfig) -> None:
        async with MySqlSession(config, AiomysqlDriverFactory()):
            return


class ProfileService:
    """Coordinate typed registry and secret-store operations."""

    def __init__(
        self,
        store: ProfileStore,
        secret_store: SecretStore | None = None,
        validator: ProfileValidator | None = None,
        *,
        working_directory: Path | None = None,
    ) -> None:
        self.store = store
        self.secret_store = secret_store or KeyringSecretStore()
        self.validator = validator or MySqlSessionValidator()
        self.working_directory = normalize_directory(working_directory or Path.cwd())

    def list_profiles(self) -> tuple[ProfileRecord, ...]:
        return self.store.read().profiles

    def require(self, name: ProfileName) -> ProfileRecord:
        profile = self.store.read().find(name)
        if profile is None:
            raise ProfileServiceError(ProfileServiceErrorCode.NOT_FOUND, "profile not found")
        return profile

    def selection(self, explicit: ProfileName | None, *, directory: Path | None = None) -> ProfileSelection:
        registry = self.store.read()
        if explicit is not None:
            profile = registry.find(explicit)
            if profile is None:
                raise ProfileServiceError(ProfileServiceErrorCode.NOT_FOUND, "profile not found")
            return ProfileSelection(profile=profile, source=ProfileSelectionSource.EXPLICIT)
        binding = registry.binding_for(directory or self.working_directory)
        if binding is None:
            raise ProfileServiceError(ProfileServiceErrorCode.NOT_FOUND, "profile not found")
        profile = registry.find(binding.profile)
        if profile is None:
            raise ProfileServiceError(ProfileServiceErrorCode.NOT_FOUND, "profile not found")
        return ProfileSelection(profile=profile, source=ProfileSelectionSource.DIRECTORY, binding=binding)

    def connection_config(self, profile: ProfileRecord) -> MySqlConnectionConfig:
        """Build a secret-safe client config for one already-selected profile."""

        if not profile.password_present:
            raise ProfileServiceError(ProfileServiceErrorCode.SECRET_MISSING, "profile secret is missing")
        password = self._get_secret(profile.name)
        if password is None:
            raise ProfileServiceError(ProfileServiceErrorCode.SECRET_MISSING, "profile secret is missing")
        settings = profile.settings
        return MySqlConnectionConfig(
            host=settings.host,
            port=settings.port,
            user=settings.user,
            password=SecretValue(_value=password),
            database=settings.database,
            charset=settings.charset,
            connect_timeout_seconds=settings.connect_timeout,
            read_timeout_seconds=settings.read_timeout,
        )

    def set(self, request: ProfileSetRequest) -> ProfileRecord:
        current_registry = self.store.read()
        existing = current_registry.find(request.name)
        if existing is None:
            if request.settings.host is None or request.settings.user is None:
                raise ProfileServiceError(ProfileServiceErrorCode.INVALID, "new profile requires host and user")
            try:
                settings = ProfileSettings(
                    host=request.settings.host,
                    port=(
                        DEFAULT_MYSQL_PORT
                        if request.settings.port is None
                        else request.settings.port
                    ),
                    user=request.settings.user,
                    database=request.settings.database,
                    charset=(
                        DEFAULT_MYSQL_CHARSET
                        if request.settings.charset is None
                        else request.settings.charset
                    ),
                    connect_timeout=(
                        DEFAULT_CONNECT_TIMEOUT_SECONDS
                        if request.settings.connect_timeout is None
                        else request.settings.connect_timeout
                    ),
                    read_timeout=(
                        DEFAULT_READ_TIMEOUT_SECONDS
                        if request.settings.read_timeout is None
                        else request.settings.read_timeout
                    ),
                )
            except ValueError as exc:
                raise ProfileServiceError(ProfileServiceErrorCode.INVALID, "profile settings are invalid") from exc
            password_present = False
        else:
            try:
                settings = request.settings.apply(existing.settings)
            except ValueError as exc:
                raise ProfileServiceError(ProfileServiceErrorCode.INVALID, "profile settings are invalid") from exc
            password_present = existing.password_present

        if request.password is not None:
            if not request.password:
                raise ProfileServiceError(ProfileServiceErrorCode.INVALID, "password cannot be empty")
            self._set_secret(request.name, request.password)
            password_present = True
        elif request.clear_password:
            self._delete_secret(request.name)
            password_present = False

        record = ProfileRecord(name=request.name, settings=settings, password_present=password_present)

        def update(registry: ProfileRegistry) -> ProfileRegistry:
            profiles = tuple(record if item.name == request.name else item for item in registry.profiles)
            if existing is None:
                profiles = (*profiles, record)
            return ProfileRegistry(profiles=profiles, bindings=registry.bindings)

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

    def unbind(self, directory: Path | None = None) -> DirectoryBinding | None:
        path = normalize_directory(directory or self.working_directory)
        removed: list[DirectoryBinding] = []

        def update(registry: ProfileRegistry) -> ProfileRegistry:
            bindings: list[DirectoryBinding] = []
            for binding in registry.bindings:
                if binding.path == path:
                    removed.append(binding)
                else:
                    bindings.append(binding)
            return ProfileRegistry(profiles=registry.profiles, bindings=tuple(bindings))

        self.store.update(update)
        return removed[0] if removed else None

    def rename(self, old: ProfileName, new: ProfileName) -> ProfileRecord:
        registry = self.store.read()
        original = registry.find(old)
        if original is None:
            raise ProfileServiceError(ProfileServiceErrorCode.NOT_FOUND, "profile not found")
        if registry.find(new) is not None:
            raise ProfileServiceError(ProfileServiceErrorCode.CONFLICT, "profile already exists")
        if original.password_present:
            password = self._get_secret(old)
            if password is None:
                raise ProfileServiceError(ProfileServiceErrorCode.SECRET_MISSING, "profile secret is missing")
            self._set_secret(new, password)

        renamed = replace(original, name=new)

        def update(current: ProfileRegistry) -> ProfileRegistry:
            if current.find(old) is None:
                raise ProfileServiceError(ProfileServiceErrorCode.NOT_FOUND, "profile not found")
            if current.find(new) is not None:
                raise ProfileServiceError(ProfileServiceErrorCode.CONFLICT, "profile already exists")
            profiles = tuple(renamed if item.name == old else item for item in current.profiles)
            bindings = tuple(
                replace(binding, profile=new) if binding.profile == old else binding for binding in current.bindings
            )
            return ProfileRegistry(profiles=profiles, bindings=bindings)

        try:
            self.store.update(update)
        except Exception:
            if original.password_present:
                self._delete_secret(new)
            raise
        if original.password_present:
            self._delete_secret(old)
        return renamed

    def remove(self, name: ProfileName) -> int:
        registry = self.store.read()
        if registry.find(name) is None:
            raise ProfileServiceError(ProfileServiceErrorCode.NOT_FOUND, "profile not found")
        removed_bindings = sum(binding.profile == name for binding in registry.bindings)

        def update(current: ProfileRegistry) -> ProfileRegistry:
            if current.find(name) is None:
                raise ProfileServiceError(ProfileServiceErrorCode.NOT_FOUND, "profile not found")
            return ProfileRegistry(
                profiles=tuple(item for item in current.profiles if item.name != name),
                bindings=tuple(item for item in current.bindings if item.profile != name),
            )

        self.store.update(update)
        self._delete_secret(name)
        return removed_bindings

    async def validate(self, name: ProfileName) -> ProfileRecord:
        profile = self.require(name)
        config = self.connection_config(profile)
        try:
            await self.validator.validate(config)
        except (ClientError, ProfileServiceError):
            raise
        except Exception as exc:
            raise ProfileServiceError(ProfileServiceErrorCode.VALIDATION_FAILED, "profile validation failed") from exc
        return profile

    def _get_secret(self, name: ProfileName) -> str | None:
        try:
            return self.secret_store.get(name)
        except SecretStoreError:
            raise ProfileServiceError(ProfileServiceErrorCode.SECRET_STORE, "secret store operation failed") from None

    def _set_secret(self, name: ProfileName, password: str) -> None:
        try:
            self.secret_store.set(name, password)
        except SecretStoreError:
            raise ProfileServiceError(ProfileServiceErrorCode.SECRET_STORE, "secret store operation failed") from None

    def _delete_secret(self, name: ProfileName) -> None:
        try:
            self.secret_store.delete(name)
        except SecretStoreError:
            raise ProfileServiceError(ProfileServiceErrorCode.SECRET_STORE, "secret store operation failed") from None


__all__ = [
    "MySqlSessionValidator",
    "ProfileService",
    "ProfileServiceError",
    "ProfileServiceErrorCode",
    "ProfileValidator",
]
