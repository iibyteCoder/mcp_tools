"""The single CLI-facing failure type shared by every Redis CLI layer."""

from __future__ import annotations

from redis_cli.enums import ErrorCode


class RedisCliError(RuntimeError):
    """An expected Redis CLI failure with a stable JSON-facing category."""

    __slots__ = ("code", "hint", "message", "retryable")

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        retryable: bool = False,
        hint: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.hint = hint


def operation_failed_error() -> RedisCliError:
    """Create the generic failure used when a driver error has no better category."""

    return RedisCliError(ErrorCode.EXECUTION_FAILED, "Redis operation failed")


__all__ = ["RedisCliError", "operation_failed_error"]
