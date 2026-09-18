"""System credential storage boundary for profile passwords."""

from __future__ import annotations

from contextlib import suppress
from typing import TYPE_CHECKING

import keyring
from keyring.errors import PasswordDeleteError

if TYPE_CHECKING:
    from mysql_cli.domain.profile import ProfileName

from mysql_cli.ports.secret_store import SecretStore, SecretStoreError


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
