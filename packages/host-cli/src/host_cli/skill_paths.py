"""Resolve the global Codex and DSH Skill document paths used by the host CLI.

The skill ships inside this repository, but an agent runtime reads it from its own
installation root. Printing both destinations lets an operator install the file
without guessing where each runtime expects it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping


class CodexEnvironmentVariable(str, Enum):
    """Environment variables that control the Codex installation root."""

    CODEX_HOME = "CODEX_HOME"


class AgentHomeDirectory(str, Enum):
    """Default user-level installation roots for supported agent runtimes."""

    CODEX = ".codex"
    DSH = ".agents"


class SkillRelativePath(str, Enum):
    """Skill paths relative to an agent installation root."""

    HOST_CLI = "skills/host-cli/SKILL.md"


@dataclass(frozen=True, slots=True)
class HostSkillPaths:
    """Global Skill document paths for both supported agent runtimes."""

    codex: Path
    dsh: Path


def resolve_codex_home(
    environment: Mapping[str, str] | None = None,
    user_home: Path | None = None,
) -> Path:
    """Resolve ``CODEX_HOME`` or the default user-level Codex directory."""

    values = os.environ if environment is None else environment
    configured_home = values.get(CodexEnvironmentVariable.CODEX_HOME.value)
    if configured_home:
        return Path(configured_home).expanduser()

    resolved_user_home = Path.home() if user_home is None else user_home
    return resolved_user_home / AgentHomeDirectory.CODEX.value


def resolve_dsh_home(user_home: Path | None = None) -> Path:
    """Resolve the default user-level DSH agent directory."""

    resolved_user_home = Path.home() if user_home is None else user_home
    return resolved_user_home / AgentHomeDirectory.DSH.value


def resolve_host_cli_skill_paths(
    environment: Mapping[str, str] | None = None,
    user_home: Path | None = None,
) -> HostSkillPaths:
    """Resolve the global Skill document paths for Codex and DSH."""

    relative_path = SkillRelativePath.HOST_CLI.value
    return HostSkillPaths(
        codex=resolve_codex_home(environment, user_home) / relative_path,
        dsh=resolve_dsh_home(user_home) / relative_path,
    )


__all__ = [
    "AgentHomeDirectory",
    "CodexEnvironmentVariable",
    "HostSkillPaths",
    "SkillRelativePath",
    "resolve_codex_home",
    "resolve_dsh_home",
    "resolve_host_cli_skill_paths",
]
