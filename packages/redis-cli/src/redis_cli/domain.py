"""Typed domain objects for Redis profiles and directory bindings."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, replace
from pathlib import Path
from urllib.parse import quote

from redis_cli.constants import (
    DEFAULT_CONNECTION_TIMEOUT_SECONDS,
    DEFAULT_REDIS_DATABASE,
    DEFAULT_REDIS_HOST,
    DEFAULT_REDIS_PORT,
    MAX_PROFILE_NAME_LENGTH,
    MAX_REDIS_PORT,
)
from redis_cli.enums import ProfileSelectionSource, RedisUrlScheme


class ProfileNameError(ValueError):
    """Raised when a profile name is not valid."""


@dataclass(frozen=True, slots=True, order=True)
class ProfileName:
    """A stable, shell-friendly profile identifier."""

    value: str

    _PATTERN = re.compile(rf"^[A-Za-z0-9][A-Za-z0-9._-]{{0,{MAX_PROFILE_NAME_LENGTH - 1}}}$")

    def __post_init__(self) -> None:
        if not self._PATTERN.fullmatch(self.value):
            raise ProfileNameError("profile name must contain 1-64 letters, numbers, '.', '_' or '-'")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class RedisSettings:
    """Non-secret Redis connection settings."""

    host: str = DEFAULT_REDIS_HOST
    port: int = DEFAULT_REDIS_PORT
    username: str = ""
    database: int = DEFAULT_REDIS_DATABASE
    connection_timeout: float = DEFAULT_CONNECTION_TIMEOUT_SECONDS
    tls: bool = False

    def __post_init__(self) -> None:
        if not self.host.strip():
            raise ValueError("host must not be empty")
        if not 1 <= self.port <= MAX_REDIS_PORT:
            raise ValueError("port must be between 1 and 65535")
        if self.database < 0:
            raise ValueError("database must be nonnegative")
        if self.connection_timeout <= 0:
            raise ValueError("connection timeout must be greater than zero")


@dataclass(frozen=True, slots=True)
class RedisConnectionConfig:
    """Resolved connection settings, including the secret at the client boundary."""

    settings: RedisSettings
    password: str = ""
    tls: bool = False

    @property
    def url(self) -> str:
        scheme = (RedisUrlScheme.REDISS if self.tls else RedisUrlScheme.REDIS).value
        username = self.settings.username
        encoded_username = quote(username, safe="")
        encoded_password = quote(self.password, safe="")
        if username and self.password:
            credentials = f"{encoded_username}:{encoded_password}"
        elif username:
            credentials = encoded_username
        elif self.password:
            credentials = f":{encoded_password}"
        else:
            credentials = ""
        authority = f"{credentials}@" if credentials else ""
        return f"{scheme}://{authority}{self.settings.host}:{self.settings.port}/{self.settings.database}"

    @classmethod
    def from_settings(
        cls,
        settings: RedisSettings,
        *,
        password: str = "",
        tls: bool | None = None,
    ) -> RedisConnectionConfig:
        """Create a client config after the settings have been validated."""

        return cls(settings=settings, password=password, tls=settings.tls if tls is None else tls)


@dataclass(frozen=True, slots=True)
class ProfileRecord:
    """A saved profile without its password."""

    name: ProfileName
    settings: RedisSettings
    description: str | None = None
    password_present: bool = False


@dataclass(frozen=True, slots=True)
class DirectoryBinding:
    """A normalized directory-to-profile association."""

    path: Path
    profile: ProfileName

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", normalize_directory(self.path))


@dataclass(frozen=True, slots=True)
class ProfileSelection:
    """A resolved profile and the source that selected it."""

    profile: ProfileRecord | None
    source: ProfileSelectionSource
    binding: DirectoryBinding | None = None


@dataclass(frozen=True, slots=True)
class ConnectionOverrides:
    """Explicit, one-invocation connection overrides."""

    url: str | None = None
    host: str | None = None
    port: int | None = None
    username: str | None = None
    password: str | None = None
    database: int | None = None
    connection_timeout: float | None = None


@dataclass(frozen=True, slots=True)
class ParsedRedisUrl:
    """The typed result of parsing one Redis URL."""

    settings: RedisSettings
    password: str
    tls: bool


@dataclass(frozen=True, slots=True)
class ResolvedConnection:
    """A connection config together with selected profile metadata."""

    config: RedisConnectionConfig
    profile: ProfileName | None
    source: ProfileSelectionSource


@dataclass(frozen=True, slots=True)
class ProfileRegistry:
    """The complete persisted registry."""

    profiles: tuple[ProfileRecord, ...] = ()
    bindings: tuple[DirectoryBinding, ...] = ()

    def __post_init__(self) -> None:
        names = [record.name for record in self.profiles]
        paths = [binding.path for binding in self.bindings]
        if len(set(names)) != len(names):
            raise ValueError("profile names must be unique")
        if len(set(paths)) != len(paths):
            raise ValueError("binding paths must be unique")
        known = set(names)
        if any(binding.profile not in known for binding in self.bindings):
            raise ValueError("bindings must refer to existing profiles")

    def find(self, name: ProfileName) -> ProfileRecord | None:
        return next((profile for profile in self.profiles if profile.name == name), None)

    def binding_for(self, directory: Path) -> DirectoryBinding | None:
        resolved = normalize_directory(directory)
        candidates = [
            binding for binding in self.bindings if resolved == binding.path or binding.path in resolved.parents
        ]
        return max(candidates, key=lambda item: len(item.path.parts), default=None)


@dataclass(frozen=True, slots=True)
class ProfileSettingsPatch:
    """Only the explicitly supplied profile settings."""

    host: str | None = None
    port: int | None = None
    username: str | None = None
    database: int | None = None
    connection_timeout: float | None = None
    tls: bool | None = None

    def apply(self, current: RedisSettings) -> RedisSettings:
        return RedisSettings(
            host=current.host if self.host is None else self.host,
            port=current.port if self.port is None else self.port,
            username=current.username if self.username is None else self.username,
            database=current.database if self.database is None else self.database,
            connection_timeout=(
                current.connection_timeout if self.connection_timeout is None else self.connection_timeout
            ),
            tls=current.tls if self.tls is None else self.tls,
        )


@dataclass(frozen=True, slots=True)
class ProfileSetRequest:
    """Input for creating or updating one profile."""

    name: ProfileName
    settings: ProfileSettingsPatch
    description: str | None = None
    clear_description: bool = False
    password: str | None = None
    clear_password: bool = False
    bind: bool = True


def normalize_directory(path: Path) -> Path:
    """Normalize a directory without requiring it to exist."""

    return Path(os.path.normcase(str(path.expanduser().resolve(strict=False))))


def replace_profile_name(record: ProfileRecord, name: ProfileName) -> ProfileRecord:
    """Return a profile with a new name."""

    return replace(record, name=name)


__all__ = [
    "ConnectionOverrides",
    "DirectoryBinding",
    "ParsedRedisUrl",
    "ProfileName",
    "ProfileNameError",
    "ProfileRecord",
    "ProfileRegistry",
    "ProfileSelection",
    "ProfileSetRequest",
    "ProfileSettingsPatch",
    "RedisConnectionConfig",
    "RedisSettings",
    "ResolvedConnection",
    "normalize_directory",
    "replace_profile_name",
]
