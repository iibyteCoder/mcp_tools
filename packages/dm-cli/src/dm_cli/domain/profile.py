"""Typed domain models for named DM profiles and directory bindings."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from db_cli_kit.profiles import (
    PROFILE_NAME_PATTERN,
    DirectoryBinding,
    ProfileName,
    normalize_directory,
)
from dm_client.domain.configuration import (
    DEFAULT_DM_PORT,
    DEFAULT_LOGIN_TIMEOUT_SECONDS,
    DEFAULT_QUERY_TIMEOUT_SECONDS,
)
from dm_client.domain.values import MAX_IDENTIFIER_LENGTH

if TYPE_CHECKING:
    from pathlib import Path


class ProfileSelectionSource(str, Enum):
    """How a command selected its profile."""

    EXPLICIT = "explicit"
    DIRECTORY = "directory"


class RegistryErrorCode(str, Enum):
    """Stable profile registry persistence failures."""

    CORRUPT = "profile_registry_corrupt"
    UNSUPPORTED_VERSION = "profile_registry_version_unsupported"
    LOCKED = "profile_registry_locked"
    IO = "profile_registry_io_error"


@dataclass(frozen=True, slots=True, kw_only=True)
class ProfileSettings:
    """Non-sensitive connection settings for one DM profile."""

    host: str
    port: int = DEFAULT_DM_PORT
    user: str = ""
    schema: str | None = None
    connect_timeout: float = DEFAULT_LOGIN_TIMEOUT_SECONDS
    query_timeout: float = DEFAULT_QUERY_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        if not self.host.strip():
            raise ValueError("host must not be empty")
        if isinstance(self.port, bool) or not 1 <= self.port <= 65_535:
            raise ValueError("port must be between 1 and 65535")
        if not self.user.strip():
            raise ValueError("user must not be empty")
        if self.schema is not None:
            if not self.schema.strip():
                raise ValueError("schema must not be blank")
            if len(self.schema) > MAX_IDENTIFIER_LENGTH:
                raise ValueError(f"schema must not exceed {MAX_IDENTIFIER_LENGTH} characters")
            if "\x00" in self.schema:
                raise ValueError("schema must not contain NUL characters")
        if self.connect_timeout <= 0:
            raise ValueError("connect timeout must be greater than zero")
        if self.query_timeout < 0:
            raise ValueError("query timeout must be zero or greater")


@dataclass(frozen=True, slots=True, kw_only=True)
class ProfileSettingsPatch:
    """Explicitly supplied profile fields; ``None`` means not supplied."""

    host: str | None = None
    port: int | None = None
    user: str | None = None
    schema: str | None = None
    connect_timeout: float | None = None
    query_timeout: float | None = None
    clear_schema: bool = False

    def apply(self, current: ProfileSettings) -> ProfileSettings:
        """Apply only fields represented by this patch."""

        return ProfileSettings(
            host=current.host if self.host is None else self.host,
            port=current.port if self.port is None else self.port,
            user=current.user if self.user is None else self.user,
            schema=None if self.clear_schema else (current.schema if self.schema is None else self.schema),
            connect_timeout=current.connect_timeout if self.connect_timeout is None else self.connect_timeout,
            query_timeout=current.query_timeout if self.query_timeout is None else self.query_timeout,
        )

    @property
    def is_empty(self) -> bool:
        """Whether no connection field was explicitly supplied."""

        fields = (self.host, self.port, self.user, self.schema, self.connect_timeout, self.query_timeout)
        return all(value is None for value in fields) and not self.clear_schema


@dataclass(frozen=True, slots=True, kw_only=True)
class ProfileRecord:
    """A profile record whose password is intentionally absent."""

    name: ProfileName
    settings: ProfileSettings
    description: str | None = None
    password_present: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class ProfileSelection:
    """Resolved profile selection for one command invocation."""

    profile: ProfileRecord
    source: ProfileSelectionSource
    binding: DirectoryBinding | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ProfileRegistry:
    """Complete typed contents of the versioned registry file."""

    profiles: tuple[ProfileRecord, ...] = ()
    bindings: tuple[DirectoryBinding, ...] = ()

    def __post_init__(self) -> None:
        names = [record.name for record in self.profiles]
        if len(set(names)) != len(names):
            raise ValueError("profile names must be unique")
        paths = [binding.path for binding in self.bindings]
        if len(set(paths)) != len(paths):
            raise ValueError("binding paths must be unique")
        known_names = set(names)
        if any(binding.profile not in known_names for binding in self.bindings):
            raise ValueError("bindings must refer to existing profiles")

    def find(self, name: ProfileName) -> ProfileRecord | None:
        """Find one profile by its validated name."""

        return next((profile for profile in self.profiles if profile.name == name), None)

    def binding_for(self, directory: Path) -> DirectoryBinding | None:
        """Return the nearest ancestor binding for ``directory``."""

        resolved = normalize_directory(directory)
        candidates = [
            binding for binding in self.bindings if resolved == binding.path or binding.path in resolved.parents
        ]
        return max(candidates, key=lambda binding: len(binding.path.parts), default=None)


@dataclass(frozen=True, slots=True, kw_only=True)
class ProfileSetRequest:
    """Typed input for ``profile set``."""

    name: ProfileName
    settings: ProfileSettingsPatch
    description: str | None = None
    clear_description: bool = False
    password: str | None = field(default=None, repr=False)
    clear_password: bool = False

    def __post_init__(self) -> None:
        if self.description is not None and self.clear_description:
            raise ValueError("description and clear_description cannot both be supplied")


__all__ = [
    "PROFILE_NAME_PATTERN",
    "DirectoryBinding",
    "ProfileName",
    "ProfileRecord",
    "ProfileRegistry",
    "ProfileSelection",
    "ProfileSelectionSource",
    "ProfileSetRequest",
    "ProfileSettings",
    "ProfileSettingsPatch",
    "RegistryErrorCode",
    "normalize_directory",
]
