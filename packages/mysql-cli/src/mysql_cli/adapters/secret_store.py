"""System credential storage boundary for profile passwords."""

from __future__ import annotations

from contextlib import suppress
from typing import TYPE_CHECKING, Protocol

import keyring
from keyring.errors import PasswordDeleteError

if TYPE_CHECKING:
    from mysql_cli.domain.profile import ProfileName


class SecretStoreError(RuntimeError):
    """A credential manager operation failed without exposing a secret."""


class SecretStore(Protocol):
    """Typed secret storage contract used by the profile service."""

    def get(self, name: ProfileName) -> str | None: ...

    def set(self, name: ProfileName, password: str) -> None: ...

    def delete(self, name: ProfileName) -> None: ...


class KeyringSecretStore:
    """Store passwords in the operating system credential manager."""

    SERVICE = "db-mysql"

    def get(self, name: ProfileName) -> str | None:
        try:
            return keyring.get_password(self.SERVICE, name.value)
        except Exception as exc:
            raise SecretStoreError("无法读取系统凭据") from exc

    def set(self, name: ProfileName, password: str) -> None:
        if not password:
            raise SecretStoreError("密码不能为空")
        try:
            keyring.set_password(self.SERVICE, name.value, password)
        except Exception as exc:
            raise SecretStoreError("无法保存系统凭据") from exc

    def delete(self, name: ProfileName) -> None:
        try:
            with suppress(PasswordDeleteError):
                keyring.delete_password(self.SERVICE, name.value)
        except Exception as exc:
            raise SecretStoreError("无法删除系统凭据") from exc


__all__ = ["KeyringSecretStore", "SecretStore", "SecretStoreError"]
