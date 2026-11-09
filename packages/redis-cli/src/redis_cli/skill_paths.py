"""Resolve the global Codex Skill location used by the Redis CLI."""

from __future__ import annotations

import os
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping


class CodexEnvironmentVariable(str, Enum):
    """Environment variables that control the Codex installation root."""

    CODEX_HOME = "CODEX_HOME"


class CodexDirectory(str, Enum):
    """Default directories used by Codex."""

    DEFAULT_HOME = ".codex"


class CodexSkillRelativePath(str, Enum):
    """Skill paths relative to the Codex installation root."""

    REDIS_CLI = "skills/redis-cli/SKILL.md"


def resolve_codex_home(
    environment: Mapping[str, str] | None = None,
    user_home: Path | None = None,
) -> Path:
    """Resolve CODEX_HOME or the default user-level Codex directory."""

    values = os.environ if environment is None else environment
    configured_home = values.get(CodexEnvironmentVariable.CODEX_HOME.value)
    if configured_home:
        return Path(configured_home).expanduser()

    resolved_user_home = Path.home() if user_home is None else user_home
    return resolved_user_home / CodexDirectory.DEFAULT_HOME.value


def resolve_redis_cli_skill_path(
    environment: Mapping[str, str] | None = None,
    user_home: Path | None = None,
) -> Path:
    """Resolve the global Redis CLI Skill document path."""

    return resolve_codex_home(environment, user_home) / CodexSkillRelativePath.REDIS_CLI.value


__all__ = [
    "CodexDirectory",
    "CodexEnvironmentVariable",
    "CodexSkillRelativePath",
    "resolve_codex_home",
    "resolve_redis_cli_skill_path",
]
