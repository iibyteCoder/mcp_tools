"""Stable JSON envelope models emitted by the Dameng CLI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, TypeAlias

from dm_cli.domain.command import CommandStatus, OutputMode

if TYPE_CHECKING:
    from pathlib import Path

    from dm_cli.application.errors import ErrorDetail
    from dm_cli.domain.command import (
        CommandAction,
        CommandGroup,
        DiagnosticStatus,
        ErrorCode,
        InputSource,
        ParameterKind,
    )
    from dm_client.domain.enums import SqlStatementType, WriteOutcome
    from dm_client.domain.results import (
        ActualPlanResult,
        AnalyzeResult,
        BenchmarkResult,
        CompareResult,
        ComparisonDifference,
        DdlResult,
        ExplainResult,
        InspectionResponse,
        QueryResult,
        WriteResult,
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class DiagnosticMetadata:
    """Stable metadata shared by success and error envelopes."""

    command_group: CommandGroup | None
    action: CommandAction | None
    input_source: InputSource | None
    output_mode: OutputMode = OutputMode.JSON


@dataclass(frozen=True, slots=True, kw_only=True)
class ProfileView:
    """Secret-free profile representation used by JSON output."""

    name: str
    description: str | None
    host: str
    port: int
    user: str
    schema: str | None
    connect_timeout: float
    query_timeout: float
    password_present: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class BindingView:
    """Serializable directory binding representation."""

    path: Path
    profile: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ProfileCommandData:
    """Successful result for one profile management operation."""

    status: CommandStatus
    command_group: CommandGroup
    action: CommandAction
    profile: ProfileView | None = None
    profiles: tuple[ProfileView, ...] = ()
    binding: BindingView | None = None
    removed_bindings: int | None = None
    unbound: bool | None = None
    validated: bool | None = None
    connection_attempted: bool | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class SqlDiagnostic:
    """Secret-free SQL parse facts returned by a local diagnostic."""

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
class ComparisonDiagnostic:
    """Secret-free parse facts for both sides of a comparison."""

    left: SqlDiagnostic | None
    right: SqlDiagnostic | None


@dataclass(frozen=True, slots=True, kw_only=True)
class CommandDiagnosticData:
    """Successful parse-only result for a command that did not contact a database."""

    status: DiagnosticStatus
    command_group: CommandGroup
    action: CommandAction
    sql: SqlDiagnostic | None
    parameters: ParameterDiagnostic | None
    comparison: ComparisonDiagnostic | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class SqlCommandData:
    """Successful output for one executed SQL command."""

    status: CommandStatus
    command_group: CommandGroup
    action: CommandAction
    profile: str
    result: ActualPlanResult | QueryResult | WriteResult | ExplainResult | BenchmarkResult | CompareResult


@dataclass(frozen=True, slots=True, kw_only=True)
class InspectionCommandData:
    """Successful output for one executed server or schema inspection."""

    status: CommandStatus
    command_group: CommandGroup
    action: CommandAction
    profile: str
    result: DdlResult | InspectionResponse | AnalyzeResult


@dataclass(frozen=True, slots=True, kw_only=True)
class PendingCommandData:
    """Explicit placeholder for command groups implemented in later batches."""

    status: CommandStatus
    command_group: CommandGroup
    action: CommandAction
    profile: str | None = None


CommandData: TypeAlias = (
    CommandDiagnosticData | ProfileCommandData | PendingCommandData | SqlCommandData | InspectionCommandData
)


@dataclass(frozen=True, slots=True, kw_only=True)
class SuccessEnvelope:
    """Top-level success envelope."""

    ok: bool
    data: CommandData
    meta: DiagnosticMetadata


@dataclass(frozen=True, slots=True, kw_only=True)
class ErrorBody:
    """Top-level structured error body."""

    code: ErrorCode
    message: str
    retryable: bool
    details: tuple[ErrorDetail, ...]
    write_outcome: WriteOutcome | None = None
    differences: tuple[ComparisonDifference, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class ErrorEnvelope:
    """Top-level error envelope."""

    ok: bool
    error: ErrorBody
    meta: DiagnosticMetadata


__all__ = [
    "BindingView",
    "CommandData",
    "CommandDiagnosticData",
    "ComparisonDiagnostic",
    "DiagnosticMetadata",
    "ErrorBody",
    "ErrorEnvelope",
    "InspectionCommandData",
    "ParameterDiagnostic",
    "PendingCommandData",
    "ProfileCommandData",
    "ProfileView",
    "SqlCommandData",
    "SqlDiagnostic",
    "SuccessEnvelope",
]
