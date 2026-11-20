"""Enumerations naming every stable value that crosses a module boundary.

Nothing here performs I/O. These members are the single source of truth for the
strings that reach JSON, ssh argument construction and error handling, so no
literal is repeated at a call site and no consumer has to guess a value's meaning
from its spelling.
"""

from __future__ import annotations

from enum import Enum, IntEnum
from typing import Final


class OutcomeKind(str, Enum):
    """The mutually exclusive result of one remote invocation.

    Exactly one of these describes every invocation. The distinction that
    matters most is whether the remote command is known to have run at all:
    only ``SUCCESS``, ``REMOTE_NONZERO_EXIT`` and ``REMOTE_KILLED_BY_SIGNAL``
    imply the command was actually started on the host.
    """

    SUCCESS = "success"
    REMOTE_NONZERO_EXIT = "remote_nonzero_exit"
    REMOTE_KILLED_BY_SIGNAL = "remote_killed_by_signal"
    TIMEOUT = "timeout"
    CREDENTIAL_STORE_UNAVAILABLE = "credential_store_unavailable"
    HOST_KEY_UNTRUSTED = "host_key_untrusted"
    AUTHENTICATION_FAILED = "authentication_failed"
    CONNECTION_FAILED = "connection_failed"
    SSH_CLIENT_UNAVAILABLE = "ssh_client_unavailable"

    @property
    def is_success(self) -> bool:
        """Return whether this outcome is reported with ``ok: true``."""

        return self is OutcomeKind.SUCCESS

    @property
    def remote_ran(self) -> bool:
        """Return whether the remote command is known to have started."""

        return self in _REMOTE_RAN_OUTCOMES


_REMOTE_RAN_OUTCOMES: Final[frozenset[OutcomeKind]] = frozenset(
    {
        OutcomeKind.SUCCESS,
        OutcomeKind.REMOTE_NONZERO_EXIT,
        OutcomeKind.REMOTE_KILLED_BY_SIGNAL,
    }
)
"""Outcomes that prove the command executed; every other one stops before that."""


class EvidenceStrength(str, Enum):
    """How firmly the observed evidence supports a classification.

    ``FALLBACK`` means no recognised signal explained the failure and the
    outcome is a best guess. Only then is the raw ssh log worth surfacing, and
    only then should a consumer treat the classification as provisional.
    """

    DECISIVE = "decisive"
    FALLBACK = "fallback"


class DangerCategory(str, Enum):
    """Why a command was flagged as irreversible or self-destructive.

    Each member names a *consequence*, not a command: several different
    commands can land in the same category, and the category is what an operator
    or a reviewer needs to reason about. Matching is advisory -- the guard
    reports what it saw and the caller decides whether ``--force`` applies.
    """

    RECURSIVE_DELETE = "recursive_delete"
    """A recursive forced delete aimed at a root, home or top-level system path."""

    DISK_WRITE = "disk_write"
    """Raw writes to a block device: ``dd of=/dev/...``, ``mkfs``, ``> /dev/sdX``."""

    POWER_STATE = "power_state"
    """Halting, rebooting or powering the machine off underneath the session."""

    PERMISSION_OPEN = "permission_open"
    """Making a whole system tree world-writable or reassigning its owner."""

    FIREWALL_FLUSH = "firewall_flush"
    """Dropping every firewall rule, which can cut the host off mid-session."""

    AUDIT_TAMPER = "audit_tamper"
    """Destroying the logs that would show what happened."""

    FORK_BOMB = "fork_bomb"
    """A recursive process explosion that starves the host."""

    ACCESS_LOCKOUT = "access_lockout"
    """Cutting off the way back in: stopping sshd, dropping the firewall, taking a
    network interface down, removing the login account, or killing init.

    Distinct from every other category because the damage is not to data but to
    reachability. A host that lost `/etc` can still be logged into; a host whose
    sshd was masked cannot, which turns a recoverable mistake into a console trip.
    """

    REDIRECT_TRUNCATE = "redirect_truncate"
    """A shell redirect that empties or overwrites a file under a system tree.

    ``echo x > /etc/passwd`` destroys the file without naming a destructive
    command, so command-name matching cannot see it. The redirect target comes
    from the syntax tree instead.
    """

    UNRESOLVED = "unresolved"
    """The command name or its target is only decided when the shell runs it.

    ``$X -rf /``, ``$(cmd) -rf /`` and similar constructions cannot be compared
    against any list. Reporting this separately keeps the guard honest: the
    caller sees that it looked and could not tell, instead of a clean result that
    merely means "not recognised".
    """


class CommandIntent(str, Enum):
    """What a command does to the machine, judged only as far as spelling allows.

    Used by read-only profiles, where the question is not "is this irreversible"
    but "could this change anything at all". The judgment is conservative in one
    direction only: anything not recognised as inspection is treated as a
    mutation, so an unknown command is refused rather than assumed harmless.
    """

    INSPECTION = "inspection"
    """Reads state: ``ps``, ``df``, ``tail``, ``systemctl status``, ``docker ps``."""

    MUTATION = "mutation"
    """Everything else, including anything the guard cannot place."""


class ApprovalState(str, Enum):
    """Where an approval request stands.

    ``GRANTED`` is the only state that permits a protected command to run, and it
    is short-lived: an approval that never expires is a permanent bypass.
    """

    REQUIRED = "required"
    GRANTED = "granted"
    EXPIRED = "expired"
    MISMATCH = "mismatch"
    """The token is valid but was issued for a different command."""


class AuditField(str, Enum):
    """Field names of one audit line.

    Declared once because the audit file is a long-lived contract read by tools
    that were not compiled against this code: a renamed field silently breaks
    every consumer, so the names are stated here and re-used everywhere.
    """

    TIMESTAMP = "timestamp"
    PROFILE = "profile"
    HOST = "host"
    USER = "user"
    COMMAND = "command"
    STATUS = "status"
    OUTCOME = "outcome"
    REMOTE_EXIT_CODE = "remote_exit_code"
    REMOTE_STATE = "remote_state"
    DURATION_MS = "duration_ms"
    STDOUT_BYTES = "stdout_bytes"
    STDERR_BYTES = "stderr_bytes"
    TRUNCATED = "truncated"
    FORCED = "forced"
    DANGER_CATEGORIES = "danger_categories"
    VERDICT = "verdict"
    REASON = "reason"


class AuditStatus(str, Enum):
    """Whether the attempt actually reached the host.

    ``BLOCKED`` records a refusal, because an attempt that never ran is still
    evidence: it shows what the operator asked for and that the guard stopped it.
    ``DRY_RUN`` records a probe that the caller deliberately did not execute, so a
    later reader cannot mistake it for a command that ran.
    """

    EXECUTED = "executed"
    BLOCKED = "blocked"
    DRY_RUN = "dry_run"


class GuardVerdict(str, Enum):
    """What the guard decided about one command.

    ``ADVISORY`` exists for the case where the command matched no irreversible
    shape but contained something the guard could not resolve -- typically a
    destructive command whose target is a variable. Reporting it separately keeps
    "checked and clean" distinguishable from "checked and blind".
    """

    CLEAR = "clear"
    BLOCKED = "blocked"
    ADVISORY = "advisory"

    @property
    def requires_force(self) -> bool:
        """Return whether this verdict stops the command without ``--force``."""

        return self is not GuardVerdict.CLEAR


class AuditWriteStatus(str, Enum):
    """Whether the audit line reached the disk.

    The command has already run by the time this is known, so a failure cannot
    undo it. Reporting the status keeps a silent evidence gap from looking like
    a clean record.
    """

    WRITTEN = "written"
    FAILED = "failed"


class HostKeyProblem(str, Enum):
    """The host key problem observed; set only on ``HOST_KEY_UNTRUSTED``.

    ``CHANGED`` is deliberately distinct from ``UNKNOWN``: a trusted key that no
    longer matches may be an impostor, whereas an unknown key is merely a first
    contact.
    """

    UNKNOWN = "unknown"
    CHANGED = "changed"


class RemoteState(str, Enum):
    """What is known about the remote command once the invocation ends.

    ``UNKNOWN`` means the host was reached but the local side gave up, so the
    process may still be running. That is not the same as never starting.
    """

    COMPLETED = "completed"
    NOT_STARTED = "not_started"
    UNKNOWN = "unknown"


class StreamEncoding(str, Enum):
    """How one captured stream is represented in the JSON document."""

    UTF8 = "utf-8"
    BINARY = "binary"


class CredentialStatus(str, Enum):
    """Whether a password is available for an invocation, and where it came from."""

    KEYRING = "keyring"
    ABSENT = "absent"


class ErrorCode(str, Enum):
    """Stable machine-readable failure categories.

    Consumers branch on this value and never on ``message``. One member per
    failing ``OutcomeKind``, plus the local failures that never reach a host.
    """

    INVALID_ARGUMENT = "invalid_argument"
    INPUT_ERROR = "input_error"
    PROFILE_NOT_FOUND = "profile_not_found"
    PROFILE_CONFLICT = "profile_conflict"
    PROFILE_REGISTRY_CORRUPT = "profile_registry_corrupt"
    PROFILE_INVALID = "profile_invalid"
    PROFILE_IO = "profile_io"
    CREDENTIAL_STORE_UNAVAILABLE = "credential_store_unavailable"
    HOST_KEY_UNTRUSTED = "host_key_untrusted"
    AUTHENTICATION_FAILED = "authentication_failed"
    CONNECTION_FAILED = "connection_failed"
    REMOTE_NONZERO_EXIT = "remote_nonzero_exit"
    REMOTE_KILLED_BY_SIGNAL = "remote_killed_by_signal"
    TIMEOUT = "timeout"
    SSH_CLIENT_UNAVAILABLE = "ssh_client_unavailable"
    DANGEROUS_COMMAND = "dangerous_command"
    READ_ONLY_VIOLATION = "read_only_violation"
    APPROVAL_REQUIRED = "approval_required"
    APPROVAL_INVALID = "approval_invalid"
    RATE_LIMITED = "rate_limited"
    INTERNAL_ERROR = "internal_error"


OUTCOME_ERROR_CODES: Final[dict[OutcomeKind, ErrorCode]] = {
    OutcomeKind.REMOTE_NONZERO_EXIT: ErrorCode.REMOTE_NONZERO_EXIT,
    OutcomeKind.REMOTE_KILLED_BY_SIGNAL: ErrorCode.REMOTE_KILLED_BY_SIGNAL,
    OutcomeKind.TIMEOUT: ErrorCode.TIMEOUT,
    OutcomeKind.CREDENTIAL_STORE_UNAVAILABLE: ErrorCode.CREDENTIAL_STORE_UNAVAILABLE,
    OutcomeKind.HOST_KEY_UNTRUSTED: ErrorCode.HOST_KEY_UNTRUSTED,
    OutcomeKind.AUTHENTICATION_FAILED: ErrorCode.AUTHENTICATION_FAILED,
    OutcomeKind.CONNECTION_FAILED: ErrorCode.CONNECTION_FAILED,
    OutcomeKind.SSH_CLIENT_UNAVAILABLE: ErrorCode.SSH_CLIENT_UNAVAILABLE,
}
"""Every failing outcome maps to exactly one error code; success maps to none."""


class ExitCode(IntEnum):
    """Process exit codes.

    The remote exit code is never reused here. It travels inside ``data`` so a
    transport failure stays distinguishable from a remote failure even in shell.
    """

    OK = 0
    FAILURE = 1


class CommandGroup(str, Enum):
    """Top-level command groups, used by the Click tree and envelope metadata."""

    PROFILE = "profile"
    RUN = "run"
    AUDIT = "audit"


class SshArgument(str, Enum):
    """OpenSSH flags the transport always passes."""

    CONFIG_FILE = "-F"
    DEBUG_LOG = "-E"
    OPTION = "-o"
    PORT = "-p"
    VERBOSE = "-vv"
    SEPARATOR = "--"


class SshOption(str, Enum):
    """OpenSSH options pinned on every invocation.

    Each value is the complete ``key=value`` pair handed to ``-o``, so the
    security posture is auditable in one place instead of being scattered across
    argv assembly.
    """

    STRICT_HOST_KEY_CHECKING = "StrictHostKeyChecking=yes"
    UPDATE_HOST_KEYS = "UpdateHostKeys=no"
    CONTROL_MASTER = "ControlMaster=no"
    CONTROL_PATH = "ControlPath=none"
    FORWARD_AGENT = "ForwardAgent=no"
    FORWARD_X11 = "ForwardX11=no"
    PERMIT_LOCAL_COMMAND = "PermitLocalCommand=no"


class SshConfig(str, Enum):
    """Values substituted into the config file and per-invocation options."""

    NO_CONFIG_FILE = "none"
    BATCH_MODE_ENABLED = "BatchMode=yes"
    BATCH_MODE_DISABLED = "BatchMode=no"
    ONE_PASSWORD_PROMPT = "NumberOfPasswordPrompts=1"


class SshBinary(str, Enum):
    """Executables the transport invokes, looked up on ``PATH`` by default."""

    SSH = "ssh"
    TASKKILL = "taskkill"


class SshAskpass(str, Enum):
    """Environment variables that make OpenSSH call the askpass helper."""

    ASKPASS = "SSH_ASKPASS"
    ASKPASS_REQUIRE = "SSH_ASKPASS_REQUIRE"
    REQUIRE_FORCE = "force"
    SECRET_PATH = "HOST_CLI_ASKPASS_SECRET"


class StderrSignal(str, Enum):
    """Recognised stderr fragments emitted by the OpenSSH client.

    Classification matches these instead of raw literals, so the accepted
    vocabulary is reviewable and a typo cannot silently disable a branch.
    """

    HOST_KEY_CHANGED = "REMOTE HOST IDENTIFICATION HAS CHANGED"
    HOST_KEY_VERIFICATION_FAILED = "Host key verification failed"
    PERMISSION_DENIED = "Permission denied"
    COULD_NOT_RESOLVE_HOSTNAME = "Could not resolve hostname"
    CONNECTION_REFUSED = "Connection refused"
    CONNECTION_TIMED_OUT = "Connection timed out"
    CONNECTION_CLOSED = "Connection closed"
    CONNECTION_RESET = "Connection reset"
    KEX_EXCHANGE = "kex_exchange_identification"
    BANNER_EXCHANGE = "banner exchange"
    BROKEN_PIPE = "Broken pipe"


CONNECTION_SIGNALS: Final[frozenset[StderrSignal]] = frozenset(
    {
        StderrSignal.COULD_NOT_RESOLVE_HOSTNAME,
        StderrSignal.CONNECTION_REFUSED,
        StderrSignal.CONNECTION_TIMED_OUT,
        StderrSignal.CONNECTION_CLOSED,
        StderrSignal.CONNECTION_RESET,
        StderrSignal.KEX_EXCHANGE,
        StderrSignal.BANNER_EXCHANGE,
        StderrSignal.BROKEN_PIPE,
    }
)
"""Fragments meaning the session never opened, i.e. ``CONNECTION_FAILED``."""


class DebugLogMarker(str, Enum):
    """Fragments of the ``-vv`` session log used to identify a session's fate.

    The transport writes the log to its own file, so these markers are available
    without polluting the remote command's stderr. ``EXIT_STATUS`` is the
    decisive one: when sshd relays a status or an exit signal, OpenSSH records it
    here, and that record cannot be confused with OpenSSH's own failure code.
    """

    AUTHENTICATED = "Authenticated to"
    EXIT_SIGNAL = "rtype exit-signal"
    EXIT_STATUS = "debug1: Exit status "
    HOST_KEY = "Server host key: "


class SshExitCode(IntEnum):
    """Process exit codes with a meaning that is specific to OpenSSH."""

    TRANSPORT_ERROR = 255
    """OpenSSH's own failure code; by status alone it is indistinguishable from
    a remote command that exited 255, which is why the debug log is consulted."""

    KILLED_BY_SIGNAL = -1
    """What OpenSSH reports after relayed ``exit-signal``. The signal number is
    not transmitted, so the specific signal cannot be named."""


class RemoteExitCode(IntEnum):
    """Limits the remote exit code is known to respect.

    sshd relays ``WEXITSTATUS``, which is eight bits wide: a remote ``exit 256``
    arrives as ``0``. The transport cannot recover the original number, so the
    CLI reports the truncated value and documents the bound.
    """

    MAX_OBSERVABLE = 254
    """Highest value relayed unchanged; 255 is reserved for OpenSSH itself."""


__all__ = [
    "CONNECTION_SIGNALS",
    "OUTCOME_ERROR_CODES",
    "ApprovalState",
    "AuditField",
    "AuditStatus",
    "AuditWriteStatus",
    "CommandGroup",
    "CommandIntent",
    "CredentialStatus",
    "DangerCategory",
    "DebugLogMarker",
    "ErrorCode",
    "EvidenceStrength",
    "ExitCode",
    "GuardVerdict",
    "HostKeyProblem",
    "OutcomeKind",
    "RemoteExitCode",
    "RemoteState",
    "SshArgument",
    "SshAskpass",
    "SshBinary",
    "SshConfig",
    "SshExitCode",
    "SshOption",
    "StderrSignal",
    "StreamEncoding",
]
