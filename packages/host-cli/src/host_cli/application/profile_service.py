"""Profile management: the registry and the credential store, kept in step."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from host_cli.domain.enums import CredentialStatus, ErrorCode
from host_cli.domain.errors import HostCliError
from host_cli.domain.models import (
    DEFAULT_COMMAND_TIMEOUT_SECONDS,
    DEFAULT_MAX_COMMANDS_PER_MINUTE,
    DEFAULT_PORT,
    ProfileRecord,
    ProfileSettings,
    ProfileView,
)

if TYPE_CHECKING:
    from db_cli_kit.profiles import ProfileName
    from host_cli.infrastructure.credentials import PasswordStore
    from host_cli.infrastructure.profile_store import ProfileStore


class ProfileService:
    """Read and mutate profiles, resolving credential state on every read.

    The registry never records whether a password exists. That fact belongs to
    the credential store alone, so this service is the one place that joins the
    two and they can never disagree.
    """

    def __init__(self, store: ProfileStore, passwords: PasswordStore) -> None:
        self._store: Final[ProfileStore] = store
        self._passwords: Final[PasswordStore] = passwords

    def list(self) -> tuple[ProfileView, ...]:
        """Return every profile with its credential presence resolved."""

        return tuple(self._to_view(record) for record in self._store.read().profiles)

    def get(self, name: ProfileName) -> ProfileView:
        """Return one profile, or fail with ``profile_not_found``."""

        return self._to_view(self.record(name))

    def record(self, name: ProfileName) -> ProfileRecord:
        """Return the stored record for ``name``, or fail when it is missing."""

        record = self._store.read().find(name)
        if record is None:
            raise HostCliError(ErrorCode.PROFILE_NOT_FOUND, f"profile {name.value!r} is not configured")
        return record

    def set(
        self,
        name: ProfileName,
        *,
        host: str | None,
        user: str | None,
        port: int | None,
        description: str | None,
        clear_description: bool,
        command_timeout: float | None,
        read_only: bool | None = None,
        max_commands_per_minute: int | None = None,
        requires_approval: bool | None = None,
    ) -> ProfileView:
        """Create or update one profile.

        Deliberately an upsert, matching the sibling CLIs: one command covers both
        creating and adjusting, and omitted fields keep their stored value so a
        caller can move a port without restating the host. The cost is that a
        misspelled name silently creates a second profile rather than failing, so
        ``profile list`` is the check after adding a host.
        """

        existing = self._store.read().find(name)
        settings = _merge_settings(
            existing.settings if existing is not None else None,
            name=name,
            host=host,
            user=user,
            port=port,
            description=description,
            clear_description=clear_description,
            command_timeout=command_timeout,
            read_only=read_only,
            max_commands_per_minute=max_commands_per_minute,
            requires_approval=requires_approval,
        )
        return self._persist(name, settings)

    def rename(self, old: ProfileName, new: ProfileName) -> ProfileView:
        """Rename a profile, carrying its settings and stored password across.

        The credential is written under the new name before the old one is
        removed, so an interruption can leave a duplicate but never a loss.
        """

        record = self.record(old)
        if self._store.read().find(new) is not None:
            raise HostCliError(ErrorCode.PROFILE_CONFLICT, f"profile {new.value!r} already exists")

        password = self._passwords.read(old)
        self._store.update(
            lambda registry: registry.remove(old).replace(ProfileRecord(name=new, settings=record.settings))
        )
        if password is not None:
            self._passwords.write(new, password)
            self._passwords.clear(old)
        return self._to_view(ProfileRecord(name=new, settings=record.settings))

    def remove(self, name: ProfileName) -> None:
        """Delete a profile and the password stored for it."""

        self.record(name)
        self._store.update(lambda registry: registry.remove(name))
        self._passwords.clear(name)

    def set_password(self, name: ProfileName, password: str) -> None:
        """Store the password of an existing profile."""

        self.record(name)
        self._passwords.write(name, password)

    def clear_password(self, name: ProfileName) -> None:
        """Forget the password of an existing profile, leaving key auth intact."""

        self.record(name)
        self._passwords.clear(name)

    def credential_status(self, view: ProfileView) -> CredentialStatus:
        """Name where the credential for ``view`` comes from."""

        return CredentialStatus.KEYRING if view.password_present else CredentialStatus.ABSENT

    def _persist(self, name: ProfileName, settings: ProfileSettings) -> ProfileView:
        """Store one record and return it with credential state resolved."""

        record = ProfileRecord(name=name, settings=settings)
        self._store.update(lambda registry: registry.replace(record))
        return self._to_view(record)

    def _to_view(self, record: ProfileRecord) -> ProfileView:
        """Attach the credential presence the store currently reports."""

        return ProfileView(
            name=record.name,
            settings=record.settings,
            password_present=self._passwords.present(record.name),
        )


def _merge_settings(
    existing: ProfileSettings | None,
    *,
    name: ProfileName,
    host: str | None,
    user: str | None,
    port: int | None,
    description: str | None,
    clear_description: bool,
    command_timeout: float | None,
    read_only: bool | None = None,
    max_commands_per_minute: int | None = None,
    requires_approval: bool | None = None,
) -> ProfileSettings:
    """Combine stored settings with the supplied changes.

    A new profile needs host and user; an existing one may change any subset.
    """

    if clear_description and description is not None:
        raise HostCliError(
            ErrorCode.INVALID_ARGUMENT,
            "--description and --no-description cannot be combined",
        )
    if existing is None and (host is None or user is None):
        raise HostCliError(
            ErrorCode.INVALID_ARGUMENT,
            f"profile {name.value!r} is new and needs both --host and --user",
        )

    try:
        return ProfileSettings(
            host=host if host is not None else _stored(existing).host,
            user=user if user is not None else _stored(existing).user,
            port=port if port is not None else _default_port(existing),
            description=_merged_description(existing, description, clear_description),
            command_timeout=(command_timeout if command_timeout is not None else _default_timeout(existing)),
            read_only=read_only if read_only is not None else _stored_flag(existing, _READ_ONLY),
            max_commands_per_minute=(
                max_commands_per_minute if max_commands_per_minute is not None else _stored_rate(existing)
            ),
            requires_approval=(
                requires_approval if requires_approval is not None else _stored_flag(existing, _REQUIRES_APPROVAL)
            ),
        )
    except ValueError as exc:
        raise HostCliError(ErrorCode.PROFILE_INVALID, str(exc)) from exc


_READ_ONLY: Final[str] = "read_only"
_REQUIRES_APPROVAL: Final[str] = "requires_approval"
"""Names of the boolean settings, referenced once rather than repeated as literals."""


def _stored_flag(existing: ProfileSettings | None, attribute: str) -> bool:
    """Return one stored boolean flag, defaulting to ``False`` for a new profile."""

    if existing is None:
        return False
    return bool(getattr(existing, attribute))


def _stored_rate(existing: ProfileSettings | None) -> int:
    """Return the stored rate ceiling, or the default for a new profile."""

    return DEFAULT_MAX_COMMANDS_PER_MINUTE if existing is None else existing.max_commands_per_minute


def _stored(existing: ProfileSettings | None) -> ProfileSettings:
    """Return stored settings, which callers must have already required."""

    if existing is None:  # pragma: no cover - guarded by _merge_settings
        raise HostCliError(ErrorCode.INTERNAL_ERROR, "missing stored settings")
    return existing


def _default_port(existing: ProfileSettings | None) -> int:
    """Return the stored port, or the default for a new profile."""

    return DEFAULT_PORT if existing is None else existing.port


def _default_timeout(existing: ProfileSettings | None) -> float:
    """Return the stored command bound, or the default for a new profile."""

    return DEFAULT_COMMAND_TIMEOUT_SECONDS if existing is None else existing.command_timeout


def _merged_description(
    existing: ProfileSettings | None,
    description: str | None,
    clear_description: bool,
) -> str | None:
    """Return the description the caller asked for, keeping a stored one by default."""

    if clear_description:
        return None
    if description is not None:
        return description
    return None if existing is None else existing.description


__all__ = ["ProfileService"]
