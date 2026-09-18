"""Secret storage boundary backed by the operating system credential manager."""

from __future__ import annotations

from contextlib import suppress
from typing import Protocol

import keyring
from keyring.errors import PasswordDeleteError

from db_cli_core.enums import DatabaseKind, ProfileStorage


class SecretStore(Protocol):
    def get(self, database_kind: DatabaseKind, profile_name: str) -> str | None: ...

    def set(self, database_kind: DatabaseKind, profile_name: str, password: str) -> None: ...

    def delete(self, database_kind: DatabaseKind, profile_name: str) -> None: ...


class SystemSecretStore:
    """Store profile passwords in Windows Credential Manager, Keychain, or Secret Service."""

    def get(self, database_kind: DatabaseKind, profile_name: str) -> str | None:
        return keyring.get_password(ProfileStorage.CREDENTIAL_SERVICE.value, self._account(database_kind, profile_name))

    def set(self, database_kind: DatabaseKind, profile_name: str, password: str) -> None:
        keyring.set_password(
            ProfileStorage.CREDENTIAL_SERVICE.value,
            self._account(database_kind, profile_name),
            password,
        )

    def delete(self, database_kind: DatabaseKind, profile_name: str) -> None:
        with suppress(PasswordDeleteError):
            keyring.delete_password(
                ProfileStorage.CREDENTIAL_SERVICE.value,
                self._account(database_kind, profile_name),
            )

    @staticmethod
    def _account(database_kind: DatabaseKind, profile_name: str) -> str:
        return f"{database_kind.value}:{profile_name}"


class VolatileSecretStore:
    """Process-local adapter for isolated tests; values are never persisted."""

    def __init__(self) -> None:
        self._passwords: dict[tuple[DatabaseKind, str], str] = {}

    def get(self, database_kind: DatabaseKind, profile_name: str) -> str | None:
        return self._passwords.get((database_kind, profile_name))

    def set(self, database_kind: DatabaseKind, profile_name: str, password: str) -> None:
        self._passwords[(database_kind, profile_name)] = password

    def delete(self, database_kind: DatabaseKind, profile_name: str) -> None:
        self._passwords.pop((database_kind, profile_name), None)
