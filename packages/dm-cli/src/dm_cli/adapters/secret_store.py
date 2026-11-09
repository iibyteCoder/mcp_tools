"""Keyring-backed credential storage for ``db-dm`` profiles."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from db_cli_kit.secrets import KeyringSecretStore as KitKeyringSecretStore
from db_cli_kit.secrets import SecretStore

if TYPE_CHECKING:
    from db_cli_kit.profiles import ProfileName

SERVICE_NAME: Final[str] = "db-dm"


class KeyringSecretStore:
    """Bind the shared keyring store to the ``db-dm`` service name."""

    SERVICE: Final[str] = SERVICE_NAME

    def __init__(self) -> None:
        self._store: SecretStore = KitKeyringSecretStore(SERVICE_NAME)

    def get(self, name: ProfileName) -> str | None:
        return self._store.get(name)

    def set(self, name: ProfileName, password: str) -> None:
        self._store.set(name, password)

    def delete(self, name: ProfileName) -> None:
        self._store.delete(name)


__all__ = ["SERVICE_NAME", "KeyringSecretStore", "SecretStore"]
