"""Stable JSON envelope models emitted by the agent-first CLI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from mysql_command.command_model import OutputMode

if TYPE_CHECKING:
    from pathlib import Path

    from mysql_client import SqlStatementType
    from mysql_command.command_model import (
        CommandAction,
        CommandGroup,
        DiagnosticStatus,
        ErrorCode,
        InputSource,
        ParameterKind,
    )
    from mysql_command.errors import ErrorDetail


@dataclass(frozen=True, slots=True, kw_only=True)
class DiagnosticMetadata:
    """Stable metadata shared by success and error envelopes."""

    command_group: CommandGroup | None
    action: CommandAction | None
    input_source: InputSource | None
    output_mode: OutputMode = OutputMode.JSON


@dataclass(frozen=True, slots=True, kw_only=True)
class SqlDiagnostic:
    """Secret-free SQL parse facts returned by the diagnostic command."""

    source: InputSource
    statement_type: SqlStatementType
    read_only: bool
    write: bool
    requires_explicit_transaction: bool
    explain_analyze: bool
    text_length: int


@dataclass(frozen=True, slots=True, kw_only=True)
class ParameterDiagnostic:
    """Secret-free parameter document facts."""

    source: InputSource
    kind: ParameterKind
    count: int
    path: Path


@dataclass(frozen=True, slots=True, kw_only=True)
class CommandDiagnosticData:
    """Successful result for this stage's parse-only command execution."""

    status: DiagnosticStatus
    command_group: CommandGroup
    action: CommandAction
    sql: SqlDiagnostic | None
    parameters: ParameterDiagnostic | None


@dataclass(frozen=True, slots=True, kw_only=True)
class SuccessEnvelope:
    """Top-level success envelope."""

    ok: bool
    data: CommandDiagnosticData
    meta: DiagnosticMetadata


@dataclass(frozen=True, slots=True, kw_only=True)
class ErrorBody:
    """Top-level structured error body."""

    code: ErrorCode
    message: str
    retryable: bool
    details: tuple[ErrorDetail, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class ErrorEnvelope:
    """Top-level error envelope."""

    ok: bool
    error: ErrorBody
    meta: DiagnosticMetadata
