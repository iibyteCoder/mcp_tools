"""Versioned, atomic persistence for the host profile registry.

The registry stores connection facts only. Whether a password exists is asked of
the credential store at read time, so the file can never disagree with the OS
keyring about it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from platformdirs import user_config_path

from db_cli_kit.atomic_json import AtomicJsonError, AtomicJsonErrorReason, AtomicJsonStore
from db_cli_kit.json_codec import JsonObject, JsonValue, is_json_object
from db_cli_kit.profiles import ProfileName
from host_cli.domain.enums import ErrorCode
from host_cli.domain.errors import HostCliError
from host_cli.domain.models import (
    DEFAULT_MAX_COMMANDS_PER_MINUTE,
    ProfileRecord,
    ProfileRegistry,
    ProfileSettings,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

REGISTRY_FILE_NAME: Final[str] = "profiles.json"
"""File name of the registry inside the per-user configuration directory."""

LOCK_TIMEOUT_SECONDS: Final[float] = 1.0
"""Seconds to wait for the registry lock before reporting a contention failure."""

TOP_LEVEL_KEYS: Final[frozenset[str]] = frozenset({"profiles"})
PROFILE_KEYS: Final[frozenset[str]] = frozenset({"name", "settings"})
REQUIRED_SETTINGS_KEYS: Final[frozenset[str]] = frozenset({"host", "user", "port", "description", "command_timeout"})
OPTIONAL_SETTINGS_KEYS: Final[frozenset[str]] = frozenset({"read_only", "max_commands_per_minute", "requires_approval"})
SETTINGS_KEYS: Final[frozenset[str]] = REQUIRED_SETTINGS_KEYS | OPTIONAL_SETTINGS_KEYS
"""Every accepted settings key.

The split exists because the three gate settings were added after registries were
already on disk. A file written before them must still load, so those keys are
optional on read while the required ones stay mandatory -- otherwise upgrading the
tool would orphan every existing profile.
"""

_ERROR_BY_REASON: Final[dict[AtomicJsonErrorReason, ErrorCode]] = {
    AtomicJsonErrorReason.CORRUPT: ErrorCode.PROFILE_REGISTRY_CORRUPT,
    AtomicJsonErrorReason.LOCKED: ErrorCode.PROFILE_IO,
    AtomicJsonErrorReason.IO: ErrorCode.PROFILE_IO,
}


def default_registry_path() -> Path:
    """Return the registry location for the current user."""

    return user_config_path("host-cli") / REGISTRY_FILE_NAME


class ProfileStore:
    """Read and replace the registry under a process-safe file lock."""

    def __init__(self, path: Path | None = None) -> None:
        self.path: Final[Path] = path or default_registry_path()
        self._store = AtomicJsonStore(self.path, LOCK_TIMEOUT_SECONDS)

    def read(self) -> ProfileRegistry:
        """Return the stored registry, or an empty one when no file exists yet."""

        try:
            document = self._store.read()
        except AtomicJsonError as exc:
            raise _translate(exc) from exc
        return ProfileRegistry() if document is None else _registry_from_document(document)

    def update(self, mutate: Callable[[ProfileRegistry], ProfileRegistry]) -> ProfileRegistry:
        """Apply ``mutate`` and persist the result under a single lock acquisition."""

        def apply(document: JsonObject | None) -> JsonObject:
            current = ProfileRegistry() if document is None else _registry_from_document(document)
            return _registry_to_document(mutate(current))

        try:
            document = self._store.update(apply)
        except AtomicJsonError as exc:
            raise _translate(exc) from exc
        return _registry_from_document(document)


def _translate(error: AtomicJsonError) -> HostCliError:
    """Map a shared persistence failure onto this CLI's stable error code."""

    return HostCliError(_ERROR_BY_REASON[error.reason], error.message)


def _corrupt() -> HostCliError:
    return HostCliError(ErrorCode.PROFILE_REGISTRY_CORRUPT, "profile registry is unreadable")


def _registry_to_document(registry: ProfileRegistry) -> JsonObject:
    profiles: list[JsonValue] = [
        {
            "name": record.name.value,
            "settings": {
                "host": record.settings.host,
                "user": record.settings.user,
                "port": record.settings.port,
                "description": record.settings.description,
                "command_timeout": record.settings.command_timeout,
                "read_only": record.settings.read_only,
                "max_commands_per_minute": record.settings.max_commands_per_minute,
                "requires_approval": record.settings.requires_approval,
            },
        }
        for record in registry.profiles
    ]
    return {"profiles": profiles}


def _registry_from_document(document: JsonObject) -> ProfileRegistry:
    if set(document) != TOP_LEVEL_KEYS:
        raise _corrupt()
    profiles_value = document.get("profiles")
    if not isinstance(profiles_value, list):
        raise _corrupt()
    return ProfileRegistry(profiles=tuple(_profile_from_document(item) for item in profiles_value))


def _profile_from_document(value: JsonValue) -> ProfileRecord:
    if not is_json_object(value) or set(value) != PROFILE_KEYS:
        raise _corrupt()
    settings_value = value.get("settings")
    if not is_json_object(settings_value):
        raise _corrupt()
    if not REQUIRED_SETTINGS_KEYS <= set(settings_value) <= SETTINGS_KEYS:
        raise _corrupt()
    try:
        return ProfileRecord(
            name=ProfileName(value=_text(value.get("name"))),
            settings=ProfileSettings(
                host=_text(settings_value.get("host")),
                user=_text(settings_value.get("user")),
                port=_integer(settings_value.get("port")),
                description=_optional_text(settings_value.get("description")),
                command_timeout=_number(settings_value.get("command_timeout")),
                read_only=_flag(settings_value.get("read_only")),
                max_commands_per_minute=_count(settings_value.get("max_commands_per_minute")),
                requires_approval=_flag(settings_value.get("requires_approval")),
            ),
        )
    except ValueError as exc:
        raise _corrupt() from exc


def _flag(value: object) -> bool:
    """Return a stored boolean, treating an absent key as ``False``."""

    if value is None:
        return False
    if isinstance(value, bool):
        return value
    raise _corrupt()


def _count(value: object) -> int:
    """Return a stored non-negative count, treating an absent key as unlimited."""

    if value is None:
        return DEFAULT_MAX_COMMANDS_PER_MINUTE
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _corrupt()
    return value


def _text(value: object) -> str:
    if not isinstance(value, str):
        raise _corrupt()
    return value


def _optional_text(value: object) -> str | None:
    if value is None or isinstance(value, str):
        return value
    raise _corrupt()


def _integer(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise _corrupt()
    return value


def _number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _corrupt()
    return float(value)


__all__ = [
    "LOCK_TIMEOUT_SECONDS",
    "OPTIONAL_SETTINGS_KEYS",
    "PROFILE_KEYS",
    "REGISTRY_FILE_NAME",
    "REQUIRED_SETTINGS_KEYS",
    "SETTINGS_KEYS",
    "TOP_LEVEL_KEYS",
    "ProfileStore",
    "default_registry_path",
]
