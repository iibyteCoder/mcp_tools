"""Operating-system credential storage boundary shared by every CLI."""

from __future__ import annotations

from contextlib import suppress
from typing import TYPE_CHECKING, Protocol

import keyring
from keyring.errors import PasswordDeleteError

if TYPE_CHECKING:
    from db_cli_kit.profiles import ProfileName


class SecretStoreError(RuntimeError):
    """A credential manager operation failed without exposing a secret."""


class SecretStore(Protocol):
    """Typed secret storage contract consumed by profile application services."""

    def get(self, name: ProfileName) -> str | None: ...

    def set(self, name: ProfileName, password: str) -> None: ...

    def delete(self, name: ProfileName) -> None: ...


class KeyringSecretStore:
    """Store passwords in the operating system credential manager."""

    def __init__(self, service: str) -> None:
        if not service.strip():
            raise ValueError("keyring service name must not be empty")
        self.service = service

    def get(self, name: ProfileName) -> str | None:
        try:
            return keyring.get_password(self.service, name.value)
        except Exception as exc:
            raise SecretStoreError("unable to read the system credential") from exc

    def set(self, name: ProfileName, password: str) -> None:
        if not password:
            raise SecretStoreError("password cannot be empty")
        try:
            keyring.set_password(self.service, name.value, password)
        except Exception as exc:
            raise SecretStoreError("unable to save the system credential") from exc

    def delete(self, name: ProfileName) -> None:
        try:
            with suppress(PasswordDeleteError):
                keyring.delete_password(self.service, name.value)
        except Exception as exc:
            raise SecretStoreError("unable to delete the system credential") from exc


__all__ = ["KeyringSecretStore", "SecretStore", "SecretStoreError"]
