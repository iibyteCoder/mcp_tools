"""Reusable profile identity and directory-binding primitives."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

PROFILE_NAME_MAX_LENGTH = 64
PROFILE_NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")


@dataclass(frozen=True, slots=True, kw_only=True)
class ProfileName:
    """A validated, immutable profile identifier shared by every CLI."""

    value: str

    def __post_init__(self) -> None:
        if not PROFILE_NAME_PATTERN.fullmatch(self.value):
            raise ValueError(
                "profile name must contain 1-64 letters, numbers, '.', '_' or '-' and start with a letter or number"
            )

    def __str__(self) -> str:
        return self.value

    def __repr__(self) -> str:
        return f"ProfileName(value={self.value!r})"


@dataclass(frozen=True, slots=True, kw_only=True)
class DirectoryBinding:
    """A normalized directory-to-profile association."""

    path: Path
    profile: ProfileName

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", normalize_directory(self.path))


def normalize_directory(path: Path) -> Path:
    """Normalize a binding path without requiring it to exist."""

    return Path(os.path.normcase(str(path.expanduser().resolve(strict=False))))


__all__ = [
    "PROFILE_NAME_MAX_LENGTH",
    "PROFILE_NAME_PATTERN",
    "DirectoryBinding",
    "ProfileName",
    "normalize_directory",
]
