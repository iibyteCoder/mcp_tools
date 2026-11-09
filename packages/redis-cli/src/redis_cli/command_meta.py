"""Envelope metadata for the command currently being executed."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from db_cli_kit.profiles import ProfileName
    from redis_cli.enums import CommandGroup


@dataclass(frozen=True, slots=True, kw_only=True)
class CommandMeta:
    """The command group, action and profile reported for one invocation."""

    group: CommandGroup | None = None
    action: str | None = None
    profile: ProfileName | None = None


__all__ = ["CommandMeta"]
