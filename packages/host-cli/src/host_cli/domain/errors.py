"""The single failure type raised across host-cli layers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from host_cli.domain.enums import ErrorCode

if TYPE_CHECKING:
    from host_cli.domain.enums import HostKeyProblem


class HostCliError(Exception):
    """An expected failure carrying a stable ``code`` and no secret material.

    ``fingerprint`` exists because a host key change must be reported with the
    key that was actually seen; without a structured field a consumer would have
    to parse prose to find it.
    """

    __slots__ = (
        "code",
        "command",
        "danger_excerpts",
        "debug_log_tail",
        "fingerprint",
        "host_key_problem",
        "message",
    )

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        host_key_problem: HostKeyProblem | None = None,
        fingerprint: str | None = None,
        debug_log_tail: tuple[str, ...] = (),
        danger_excerpts: tuple[str, ...] = (),
        command: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.host_key_problem = host_key_problem
        self.fingerprint = fingerprint
        self.debug_log_tail = debug_log_tail
        self.danger_excerpts = danger_excerpts
        self.command = command


def profile_not_found(name: str) -> HostCliError:
    """Build the failure reported when a selected profile does not exist."""

    return HostCliError(ErrorCode.PROFILE_NOT_FOUND, f"profile {name!r} is not configured")


def profile_conflict(name: str) -> HostCliError:
    """Build the failure reported when a name is already taken."""

    return HostCliError(ErrorCode.PROFILE_CONFLICT, f"profile {name!r} already exists")


def invalid_argument(message: str) -> HostCliError:
    """Build the failure reported for unusable command line input."""

    return HostCliError(ErrorCode.INVALID_ARGUMENT, message)


def input_error(message: str) -> HostCliError:
    """Build the failure reported for unusable standard input."""

    return HostCliError(ErrorCode.INPUT_ERROR, message)


def internal_error(message: str) -> HostCliError:
    """Build the failure reported for an unexpected internal fault."""

    return HostCliError(ErrorCode.INTERNAL_ERROR, message)


__all__ = [
    "HostCliError",
    "input_error",
    "internal_error",
    "invalid_argument",
    "profile_conflict",
    "profile_not_found",
]
