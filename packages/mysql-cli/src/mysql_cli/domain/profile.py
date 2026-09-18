"""Typed domain models for named MySQL profiles and directory bindings."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from mysql_client.domain.configuration import (
    DEFAULT_CONNECT_TIMEOUT_SECONDS,
    DEFAULT_MYSQL_CHARSET,
    DEFAULT_MYSQL_PORT,
    DEFAULT_READ_TIMEOUT_SECONDS,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class ProfileName:
    """Validated, immutable profile identifier."""

    _PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
    value: str

    def __post_init__(self) -> None:
        if not self._PATTERN.fullmatch(self.value):
            raise ValueError("profile name must contain 1-64 letters, numbers, '.', '_' or '-'")

    def __str__(self) -> str:
        return self.value

    def __repr__(self) -> str:
        return f"ProfileName(value={self.value!r})"


class ProfileSelectionSource(str, Enum):
    """How a command selected its profile."""

    EXPLICIT = "explicit"
    DIRECTORY = "directory"


class RegistryErrorCode(str, Enum):
    """Stable persistence failures."""

    CORRUPT = "profile_registry_corrupt"
    UNSUPPORTED_VERSION = "profile_registry_version_unsupported"
    LOCKED = "profile_registry_locked"
    IO = "profile_registry_io_error"


@dataclass(frozen=True, slots=True, kw_only=True)
class ProfileSettings:
    """Non-sensitive connection settings for one MySQL profile."""

    host: str
    port: int = DEFAULT_MYSQL_PORT
    user: str = ""
    database: str | None = None
    charset: str = DEFAULT_MYSQL_CHARSET
    connect_timeout: float = DEFAULT_CONNECT_TIMEOUT_SECONDS
    read_timeout: float = DEFAULT_READ_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        if not self.host.strip():
            raise ValueError("host must not be empty")
        if not 1 <= self.port <= 65_535:
            raise ValueError("port must be between 1 and 65535")
        if not self.user.strip():
            raise ValueError("user must not be empty")
        if not self.charset.strip():
            raise ValueError("charset must not be empty")
        if self.connect_timeout <= 0 or self.read_timeout <= 0:
            raise ValueError("timeouts must be greater than zero")


@dataclass(frozen=True, slots=True, kw_only=True)
class ProfileSettingsPatch:
    """Explicitly supplied profile fields; ``None`` means not supplied."""

    host: str | None = None
    port: int | None = None
    user: str | None = None
    database: str | None = None
    charset: str | None = None
    connect_timeout: float | None = None
    read_timeout: float | None = None
    clear_database: bool = False

    def apply(self, current: ProfileSettings) -> ProfileSettings:
        """Apply only fields represented by this patch."""

        return ProfileSettings(
            host=current.host if self.host is None else self.host,
            port=current.port if self.port is None else self.port,
            user=current.user if self.user is None else self.user,
            database=None if self.clear_database else (current.database if self.database is None else self.database),
            charset=current.charset if self.charset is None else self.charset,
            connect_timeout=current.connect_timeout if self.connect_timeout is None else self.connect_timeout,
            read_timeout=current.read_timeout if self.read_timeout is None else self.read_timeout,
        )

    @property
    def is_empty(self) -> bool:
        """Whether no connection field was explicitly supplied."""

        return (
            all(
                value is None
                for value in (
                    self.host,
                    self.port,
                    self.user,
                    self.database,
                    self.charset,
                    self.connect_timeout,
                    self.read_timeout,
                )
            )
            and not self.clear_database
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class DirectoryBinding:
    """A normalized directory-to-profile association."""

    path: Path
    profile: ProfileName

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", normalize_directory(self.path))


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


def normalize_directory(path: Path) -> Path:
    """Normalize a binding path without requiring it to exist."""

    return Path(os.path.normcase(str(path.expanduser().resolve(strict=False))))


__all__ = [
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
