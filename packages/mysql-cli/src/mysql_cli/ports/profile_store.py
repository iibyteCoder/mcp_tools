"""Persistence contract for the profile registry."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Callable

    from mysql_cli.domain.profile import ProfileRegistry, RegistryErrorCode


class ProfileStoreError(RuntimeError):
    """A stable, secret-free profile registry persistence error."""

    def __init__(self, code: RegistryErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ProfileStore(Protocol):
    """Typed store contract used by the profile application service."""

    def read(self) -> ProfileRegistry: ...

    def write(self, registry: ProfileRegistry) -> None: ...

    def update(self, updater: Callable[[ProfileRegistry], ProfileRegistry]) -> ProfileRegistry: ...


__all__ = ["ProfileStore", "ProfileStoreError"]
