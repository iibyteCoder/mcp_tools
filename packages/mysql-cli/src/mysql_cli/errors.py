"""Typed CLI failures and their stable JSON-facing detail models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from mysql_cli.command_model import DiagnosticErrorType, ErrorCode, ExitCode, InputSource


@dataclass(frozen=True, slots=True, kw_only=True)
class ErrorDetail:
    """Structured, secret-free context for one CLI failure."""

    error_type: DiagnosticErrorType
    argument: str | None = None
    source: InputSource | None = None
    path: Path | None = None


class CliFailure(Exception):
    """An expected failure that can be rendered without writing to stderr."""

    __slots__ = ("code", "details", "exit_code", "message", "retryable")

    def __init__(
        self,
        *,
        code: ErrorCode,
        message: str,
        retryable: bool,
        details: tuple[ErrorDetail, ...],
        exit_code: ExitCode,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.details = details
        self.exit_code = exit_code
