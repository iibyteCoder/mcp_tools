"""OS credential-manager boundary for Redis passwords."""

from __future__ import annotations

from contextlib import suppress
from typing import TYPE_CHECKING, Protocol

import keyring
from keyring.errors import PasswordDeleteError

from redis_cli.constants import PASSWORD_SERVICE_NAME

if TYPE_CHECKING:
    from redis_cli.domain import ProfileName


class SecretStoreError(RuntimeError):
    """Raised when a password cannot be read or written."""


class SecretStore(Protocol):
    """Typed credential-store boundary consumed by the profile service."""

    def get(self, name: ProfileName) -> str | None: ...

    def set(self, name: ProfileName, password: str) -> None: ...

    def delete(self, name: ProfileName) -> None: ...


class KeyringSecretStore:
    """Store passwords under the shared db-cli service."""

    SERVICE = PASSWORD_SERVICE_NAME

    def get(self, name: ProfileName) -> str | None:
        try:
            return keyring.get_password(self.SERVICE, name.value)
        except Exception as exc:
            raise SecretStoreError("unable to read the system credential") from exc

    def set(self, name: ProfileName, password: str) -> None:
        if not password:
            raise SecretStoreError("password cannot be empty")
        try:
            keyring.set_password(self.SERVICE, name.value, password)
        except Exception as exc:
            raise SecretStoreError("unable to save the system credential") from exc

    def delete(self, name: ProfileName) -> None:
        try:
            with suppress(PasswordDeleteError):
                keyring.delete_password(self.SERVICE, name.value)
        except Exception as exc:
            raise SecretStoreError("unable to delete the system credential") from exc


__all__ = ["KeyringSecretStore", "SecretStore", "SecretStoreError"]
