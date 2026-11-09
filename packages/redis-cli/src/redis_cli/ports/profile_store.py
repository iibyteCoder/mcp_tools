"""Persistence contract for the Redis profile registry."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Callable

    from redis_cli.domain.profiles import ProfileRegistry


class ProfileStore(Protocol):
    """Typed store contract used by the profile application service."""

    def read(self) -> ProfileRegistry: ...

    def update(self, updater: Callable[[ProfileRegistry], ProfileRegistry]) -> ProfileRegistry: ...


__all__ = ["ProfileStore"]
