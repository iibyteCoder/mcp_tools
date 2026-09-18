"""Credential storage contract for profile passwords."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from mysql_cli.domain.profile import ProfileName


class SecretStoreError(RuntimeError):
    """A credential manager operation failed without exposing a secret."""


class SecretStore(Protocol):
    """Typed secret storage contract used by the profile application service."""

    def get(self, name: ProfileName) -> str | None: ...

    def set(self, name: ProfileName, password: str) -> None: ...

    def delete(self, name: ProfileName) -> None: ...


__all__ = ["SecretStore", "SecretStoreError"]
