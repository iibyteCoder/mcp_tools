"""Short-lived approvals for commands a profile marks as needing one.

An approval is a token bound to one command and one profile, stored on disk with
an expiry. It exists because the alternative -- a permanent ``--force`` -- cannot
distinguish a decision someone made from a habit.

The token is a digest of the command, not a random value: that binding is what
makes it unusable for any other command, and it means the approval record cannot
be transplanted even by editing the file. The expiry is what stops an approval
from becoming a standing permission.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Final

from host_cli.domain.enums import ApprovalState
from host_cli.domain.models import APPROVAL_TTL_SECONDS

if TYPE_CHECKING:
    from pathlib import Path

    from db_cli_kit.profiles import ProfileName

APPROVAL_FILE_NAME: Final[str] = "approvals.json"
"""Where issued approvals are kept, beside the profile registry."""

TOKEN_DIGITS: Final[int] = 8
"""Characters in a token: enough to be unguessable for a 10-minute window."""


@dataclass(frozen=True, slots=True)
class Approval:
    """One issued approval: which command, for which profile, until when."""

    profile: str
    command_digest: str
    token: str
    issued_at: datetime
    expires_at: datetime

    @property
    def expired(self) -> bool:
        """Return whether this approval is past its expiry."""

        return datetime.now(timezone.utc) >= self.expires_at


def digest(command: str) -> str:
    """Return the stable digest an approval is bound to."""

    return hashlib.sha256(command.encode("utf-8")).hexdigest()


def issue(
    *,
    path: Path,
    profile: ProfileName,
    command: str,
    ttl_seconds: float = APPROVAL_TTL_SECONDS,
) -> Approval:
    """Issue an approval for one command and persist it.

    Only a digest of the command is stored. The command itself never enters this
    file, so an approval record cannot leak what was about to run.
    """

    now = datetime.now(timezone.utc)
    approval = Approval(
        profile=profile.value,
        command_digest=digest(command),
        token=secrets.token_hex(TOKEN_DIGITS),
        issued_at=now,
        expires_at=now + timedelta(seconds=ttl_seconds),
    )
    approvals = [existing for existing in read(path) if not existing.expired]
    approvals.append(approval)
    _write(path, approvals)
    return approval


def check(
    *,
    path: Path,
    profile: ProfileName,
    command: str,
    token: str,
) -> ApprovalState:
    """Return whether ``token`` authorises ``command`` on ``profile``.

    Each failure is reported distinctly because the response differs: an expired
    approval needs re-issuing, a mismatched one means the wrong command is about
    to run, and a missing one means no approval was ever requested.
    """

    wanted = token.strip().lower()
    for approval in read(path):
        if approval.token != wanted or approval.profile != profile.value:
            continue
        if approval.expired:
            return ApprovalState.EXPIRED
        if approval.command_digest != digest(command):
            return ApprovalState.MISMATCH
        return ApprovalState.GRANTED
    return ApprovalState.REQUIRED


def read(path: Path) -> tuple[Approval, ...]:
    """Return every stored approval, skipping entries that cannot be read.

    A damaged file yields nothing rather than raising: the consequence of an
    unreadable approval file must be "no approval", never "approval granted".
    """

    if not path.exists():
        return ()
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ()
    entries = document.get("approvals") if isinstance(document, dict) else None
    if not isinstance(entries, list):
        return ()
    approvals: list[Approval] = []
    for entry in entries:
        approval = _to_approval(entry)
        if approval is not None:
            approvals.append(approval)
    return tuple(approvals)


def _to_approval(entry: object) -> Approval | None:
    """Convert one stored entry, or ``None`` when it is malformed."""

    if not isinstance(entry, dict):
        return None
    try:
        return Approval(
            profile=str(entry["profile"]),
            command_digest=str(entry["command_digest"]),
            token=str(entry["token"]),
            issued_at=datetime.fromisoformat(str(entry["issued_at"])),
            expires_at=datetime.fromisoformat(str(entry["expires_at"])),
        )
    except (KeyError, ValueError):
        return None


def _write(path: Path, approvals: list[Approval]) -> None:
    """Replace the approval file atomically."""

    path.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "approvals": [
            {
                "profile": approval.profile,
                "command_digest": approval.command_digest,
                "token": approval.token,
                "issued_at": approval.issued_at.isoformat(),
                "expires_at": approval.expires_at.isoformat(),
            }
            for approval in approvals
        ]
    }
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(document, indent=2), encoding="utf-8")
    temporary.replace(path)


__all__ = ["APPROVAL_FILE_NAME", "Approval", "check", "digest", "issue", "read"]
