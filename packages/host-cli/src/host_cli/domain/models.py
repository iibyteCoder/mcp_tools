"""Named value objects for profiles, invocation bounds, streams and results."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

from host_cli.domain.enums import (
    DangerCategory,
    ErrorCode,
    EvidenceStrength,
    GuardVerdict,
    HostKeyProblem,
    OutcomeKind,
    RemoteState,
    StreamEncoding,
)

if TYPE_CHECKING:
    from db_cli_kit.profiles import ProfileName
    from host_cli.domain.danger import DangerFinding

DEFAULT_PORT: Final[int] = 22
"""SSH port assumed when a profile does not override it."""

MAX_PORT: Final[int] = 65_535

DEFAULT_CONNECT_TIMEOUT_SECONDS: Final[float] = 10.0
"""Bound for reaching the host and finishing authentication."""

DEFAULT_COMMAND_TIMEOUT_SECONDS: Final[float] = 60.0
"""Bound for the remote command once the session is established."""

DEFAULT_MAX_STREAM_BYTES: Final[int] = 1_048_576
"""Bytes kept per stream; the excess is counted and dropped, never hidden."""

DEFAULT_MAX_COMMANDS_PER_MINUTE: Final[int] = 0
"""Rate ceiling when a profile does not set one. ``0`` means unlimited.

Unlimited is the default because a human occasionally running three commands is
not the risk; an agent stuck in a retry loop is, and that is a property of the
caller rather than of every profile. Setting the ceiling is a deliberate choice
per host.
"""

APPROVAL_TTL_SECONDS: Final[float] = 600.0
"""How long a granted approval stays usable.

Short enough that a token left in a shell history expires before anyone reuses
it by accident, long enough that a human can read the command and decide.
"""


@dataclass(frozen=True, slots=True)
class ProfileSettings:
    """The non-secret connection facts of one profile."""

    host: str
    user: str
    port: int = DEFAULT_PORT
    description: str | None = None
    command_timeout: float = DEFAULT_COMMAND_TIMEOUT_SECONDS
    read_only: bool = False
    max_commands_per_minute: int = DEFAULT_MAX_COMMANDS_PER_MINUTE
    requires_approval: bool = False

    def __post_init__(self) -> None:
        """Reject settings that could not address a usable ssh target."""

        if not self.host.strip():
            raise ValueError("host must not be empty")
        if not self.user.strip():
            raise ValueError("user must not be empty")
        if not 1 <= self.port <= MAX_PORT:
            raise ValueError(f"port must be between 1 and {MAX_PORT}")
        if self.command_timeout <= 0:
            raise ValueError("command timeout must be greater than zero")
        if self.max_commands_per_minute < 0:
            raise ValueError("the rate ceiling must not be negative")


@dataclass(frozen=True, slots=True)
class ProfileRecord:
    """One profile exactly as persisted. The password lives in the keyring."""

    name: ProfileName
    settings: ProfileSettings


@dataclass(frozen=True, slots=True)
class ProfileView:
    """A profile plus credential presence, resolved at read time.

    ``password_present`` is never persisted: the registry cannot then claim a
    password the credential store no longer holds.
    """

    name: ProfileName
    settings: ProfileSettings
    password_present: bool


@dataclass(frozen=True, slots=True)
class ProfileRegistry:
    """Every stored profile, in the order the store serialised them."""

    profiles: tuple[ProfileRecord, ...] = ()

    def find(self, name: ProfileName) -> ProfileRecord | None:
        """Return the record stored under ``name``, if any."""

        return next((record for record in self.profiles if record.name == name), None)

    def replace(self, record: ProfileRecord) -> ProfileRegistry:
        """Return a registry with ``record`` inserted, replacing one of that name."""

        kept = tuple(existing for existing in self.profiles if existing.name != record.name)
        return ProfileRegistry(profiles=(*kept, record))

    def remove(self, name: ProfileName) -> ProfileRegistry:
        """Return a registry without the profile called ``name``."""

        return ProfileRegistry(profiles=tuple(item for item in self.profiles if item.name != name))


@dataclass(frozen=True, slots=True)
class StreamCapture:
    """One captured stream: decoded text or base64 bytes, never both."""

    encoding: StreamEncoding
    text: str | None
    base64: str | None
    bytes: int
    dropped_bytes: int

    @property
    def truncated(self) -> bool:
        """Return whether any byte of this stream was dropped."""

        return self.dropped_bytes > 0


@dataclass(frozen=True, slots=True)
class InvocationLimits:
    """The bounds applied to one remote invocation."""

    connect_timeout: float = DEFAULT_CONNECT_TIMEOUT_SECONDS
    command_timeout: float = DEFAULT_COMMAND_TIMEOUT_SECONDS
    max_stream_bytes: int = DEFAULT_MAX_STREAM_BYTES


@dataclass(frozen=True, slots=True)
class RawExecution:
    """What the transport observed, before any interpretation happens."""

    exit_code: int
    stdout: bytes
    stderr: bytes
    stdout_dropped: int
    stderr_dropped: int
    duration_ms: int
    timed_out: bool
    spawn_failed: bool
    debug_log: str


@dataclass(frozen=True, slots=True)
class Outcome:
    """One classified result, the evidence that identified it and how firm it is."""

    kind: OutcomeKind
    evidence: EvidenceStrength = EvidenceStrength.DECISIVE
    host_key_problem: HostKeyProblem | None = None


@dataclass(frozen=True, slots=True)
class RunResult:
    """A finished invocation, ready to be rendered."""

    profile: ProfileName
    command: str
    outcome: Outcome
    remote_exit_code: int | None
    remote_state: RemoteState
    duration_ms: int
    stdout: StreamCapture
    stderr: StreamCapture
    fingerprint: str | None = None
    debug_log_tail: tuple[str, ...] = field(default=())
    danger_categories: tuple[DangerCategory, ...] = field(default=())
    forced: bool = False
    verdict: GuardVerdict = GuardVerdict.CLEAR


@dataclass(frozen=True, slots=True)
class GatePrediction:
    """What a dry run says about the gates a command would have to pass.

    ``reason`` names the first gate that would refuse, so a caller learns which
    one to satisfy rather than just that something would stop it. ``None`` means
    every gate would let the command through.
    """

    report: DangerReport
    reason: ErrorCode | None

    @property
    def would_block(self) -> bool:
        """Return whether any gate would refuse the command without changes."""

        return self.reason is not None


@dataclass(frozen=True, slots=True)
class DangerReport:
    """What the guard found in one command, and what it decided.

    A report is produced for every invocation, even a clean one, so the caller
    can see that the check ran rather than infer it from silence.
    """

    findings: tuple[DangerFinding, ...]
    verdict: GuardVerdict
    forced: bool = False

    @property
    def categories(self) -> tuple[DangerCategory, ...]:
        """Return the matched categories in report order."""

        return tuple(finding.category for finding in self.findings)

    @property
    def blocked(self) -> bool:
        """Return whether the command may not run without ``--force``.

        A forced invocation still carries its findings, so the audit trail can
        show what was overridden, but it is no longer blocked.
        """

        return not self.forced and self.verdict.requires_force


__all__ = [
    "DEFAULT_COMMAND_TIMEOUT_SECONDS",
    "DEFAULT_CONNECT_TIMEOUT_SECONDS",
    "DEFAULT_MAX_STREAM_BYTES",
    "DEFAULT_PORT",
    "MAX_PORT",
    "DangerReport",
    "InvocationLimits",
    "Outcome",
    "ProfileRecord",
    "ProfileRegistry",
    "ProfileSettings",
    "ProfileView",
    "RawExecution",
    "RunResult",
    "StreamCapture",
]
