"""A per-profile ceiling on how many commands may be sent in one minute.

This guards a different failure from the danger guard: not "this command is
wrong" but "this caller will not stop". An agent stuck in a retry loop can send
hundreds of harmless commands and still take a host down, and no single one of
them looks dangerous.

The window is a sliding minute rather than a fixed bucket, because a fixed bucket
lets a caller send the full allowance at 12:00:59 and again at 12:01:00. Timestamps
are recorded before the command runs, so a command that times out still counts.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from pathlib import Path

    from db_cli_kit.profiles import ProfileName

RATE_FILE_NAME: Final[str] = "rate.json"
"""Where the recent-invocation timestamps are kept."""

WINDOW_SECONDS: Final[int] = 60
"""The sliding window the ceiling is measured over."""

MAX_ENTRIES_PER_PROFILE: Final[int] = 512
"""Bound on stored timestamps, so the file cannot grow without limit."""


def consume(*, path: Path, profile: ProfileName, limit: int) -> bool:
    """Record one invocation and return whether it is within ``limit``.

    ``limit`` of ``0`` means unlimited, and the call still succeeds without
    writing anything: a profile that opted out should not pay for the accounting.

    A verdict of ``False`` means the invocation must be refused. The timestamp is
    recorded either way, so a refused caller cannot escape the ceiling by
    retrying immediately.
    """

    if limit <= 0:
        return True

    now = datetime.now(timezone.utc)
    recent = _prune(_read(path).get(profile.value, ()), now)
    within_limit = len(recent) < limit
    _write(path, _merged(path, profile.value, (*recent, now)))
    return within_limit


def remaining(*, path: Path, profile: ProfileName, limit: int) -> int:
    """Return how many invocations this profile may still make in the window."""

    if limit <= 0:
        return limit
    recent = _prune(_read(path).get(profile.value, ()), datetime.now(timezone.utc))
    return max(limit - len(recent), 0)


def _prune(timestamps: tuple[datetime, ...], now: datetime) -> tuple[datetime, ...]:
    """Drop timestamps that have fallen outside the window, keeping the newest."""

    cutoff = now - timedelta(seconds=WINDOW_SECONDS)
    recent = tuple(stamp for stamp in timestamps if stamp > cutoff)
    return recent[-MAX_ENTRIES_PER_PROFILE:]


def _read(path: Path) -> dict[str, tuple[datetime, ...]]:
    """Return the stored timestamps per profile, or nothing when unreadable.

    An unreadable file is treated as empty rather than fatal: the ceiling is a
    safety net, and refusing every command because the counter is damaged would
    be a worse failure than briefly not counting.
    """

    if not path.exists():
        return {}
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(document, dict):
        return {}
    parsed: dict[str, tuple[datetime, ...]] = {}
    for profile, stamps in document.items():
        if not isinstance(stamps, list):
            continue
        parsed[str(profile)] = tuple(stamp for stamp in (_to_datetime(value) for value in stamps) if stamp is not None)
    return parsed


def _to_datetime(value: object) -> datetime | None:
    """Convert one stored timestamp, or ``None`` when it cannot be read."""

    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _merged(path: Path, profile: str, stamps: tuple[datetime, ...]) -> dict[str, list[str]]:
    """Return the document to write, with one profile's timestamps replaced."""

    document = {name: [stamp.isoformat() for stamp in values] for name, values in _read(path).items()}
    document[profile] = [stamp.isoformat() for stamp in stamps]
    return document


def _write(path: Path, document: dict[str, list[str]]) -> None:
    """Replace the rate file atomically."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(document), encoding="utf-8")
    temporary.replace(path)


__all__ = ["RATE_FILE_NAME", "WINDOW_SECONDS", "consume", "remaining"]
