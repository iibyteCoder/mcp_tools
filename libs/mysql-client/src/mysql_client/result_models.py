"""Immutable results and error data owned by the MySQL client domain."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, TypeAlias

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import datetime

    from mysql_client.enums import ErrorCode, ExplainFormat, InspectionCommand, SqlStatementType
    from mysql_client.value_models import DatabaseValue


@dataclass(frozen=True, slots=True, kw_only=True)
class TargetMetadata:
    """Secret-free identity and server details for an execution target."""

    label: str
    host: str | None = None
    port: int | None = None
    database: str | None = None
    server_version: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ColumnDefinition:
    """Description of one result column."""

    name: str
    type_name: str
    nullable: bool = True
    ordinal: int = 0
    default: DatabaseValue | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class DatabaseRow:
    """One ordered result row with explicitly typed database values."""

    values: tuple[DatabaseValue, ...]

    @classmethod
    def from_values(cls, values: Iterable[DatabaseValue]) -> DatabaseRow:
        return cls(values=tuple(values))


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionMetadata:
    """Measurements and target identity attached to an execution result."""

    statement_type: SqlStatementType
    duration_ms: float
    row_count: int = 0
    affected_rows: int = 0
    target: TargetMetadata | None = None
    started_at: datetime | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class QueryResult:
    """Tabular read result with an explicit truncation marker."""

    columns: tuple[ColumnDefinition, ...]
    rows: tuple[DatabaseRow, ...]
    metadata: ExecutionMetadata
    truncated: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class WriteResult:
    """Result of a write or DDL operation."""

    affected_rows: int
    metadata: ExecutionMetadata
    generated_values: tuple[DatabaseValue, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class ExplainResult:
    """Execution plan rows and their format."""

    format: ExplainFormat
    columns: tuple[ColumnDefinition, ...]
    rows: tuple[DatabaseRow, ...]
    metadata: ExecutionMetadata


@dataclass(frozen=True, slots=True, kw_only=True)
class BenchmarkResult:
    """Repeated execution timings in milliseconds."""

    samples_ms: tuple[float, ...]
    metadata: ExecutionMetadata


@dataclass(frozen=True, slots=True, kw_only=True)
class CompareResult:
    """Presentation-neutral comparison outcome."""

    equal: bool
    left: QueryResult
    right: QueryResult
    differences: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class InspectionResult:
    """Typed result for one server or schema inspection query."""

    command: InspectionCommand
    query: QueryResult


@dataclass(frozen=True, slots=True, kw_only=True)
class ErrorReport:
    """Stable structured error data without process or presentation policy."""

    code: ErrorCode
    message: str
    hint: str | None = None
    exception_type: str | None = None


ResponsePayload: TypeAlias = (
    QueryResult
    | WriteResult
    | ExplainResult
    | BenchmarkResult
    | CompareResult
    | InspectionResult
)
