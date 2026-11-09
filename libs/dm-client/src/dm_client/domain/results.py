"""Immutable results owned by the Dameng client domain."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, TypeAlias

from dm_client.domain.enums import PlanParseStatus, WriteOutcome
from dm_client.domain.values import JsonScalar

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import datetime

    from dm_client.domain.enums import (
        ComparisonDifferenceKind,
        ComparisonLocation,
        InspectionKind,
        ObjectType,
        SqlStatementType,
    )
    from dm_client.domain.values import DatabaseValue

PLAN_FORMAT_TEXT: Final[str] = "text"
PLAN_FIRST_LINE_INDENT: Final[int] = 0


@dataclass(frozen=True, slots=True, kw_only=True)
class TargetMetadata:
    """Secret-free identity and server details for an execution target."""

    label: str
    host: str | None = None
    port: int | None = None
    schema: str | None = None
    server_version: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ColumnDefinition:
    """Description of one result column."""

    name: str
    type_name: str
    nullable: bool = True
    ordinal: int = 0


@dataclass(frozen=True, slots=True, kw_only=True)
class DatabaseRow:
    """One ordered result row with explicitly typed database values."""

    values: tuple[DatabaseValue, ...]

    @classmethod
    def from_values(cls, values: Iterable[DatabaseValue]) -> DatabaseRow:
        """Build one row from any iterable of typed values."""

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
    """Result of a write or DDL operation with explicit commit semantics."""

    affected_rows: int
    metadata: ExecutionMetadata
    outcome: WriteOutcome = WriteOutcome.COMMITTED
    ddl_auto_commit: bool = False
    generated_values: tuple[DatabaseValue, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class PlanNode:
    """One best-effort parsed line of a DM text execution plan."""

    line: int
    depth: int
    operation: str
    text: str
    cost: float | None = None
    estimated_rows: int | None = None
    estimated_bytes: int | None = None
    detail: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ExplainResult:
    """Authoritative plan text plus best-effort parsed nodes."""

    plan_text: str
    metadata: ExecutionMetadata
    parse_status: PlanParseStatus = PlanParseStatus.PARSED
    parse_warning: str | None = None
    nodes: tuple[PlanNode, ...] = ()
    format: str = PLAN_FORMAT_TEXT


@dataclass(frozen=True, slots=True, kw_only=True)
class PlanStatistic:
    """One actual aggregate statistic from a disql autotrace ``Statistics`` block."""

    name: str
    value: int


@dataclass(frozen=True, slots=True, kw_only=True)
class ActualPlanResult:
    """Estimated plan text paired with actual aggregate runtime statistics.

    ``plan_text`` is the estimated optimizer plan reported by disql autotrace;
    it is not a per-operator actual plan. ``statistics`` and
    ``statistics_text`` are the actual aggregate ``Statistics`` block, which
    contains no per-operator time or loop counts.
    """

    provider: str
    executed: bool
    plan_text: str
    statistics: tuple[PlanStatistic, ...]
    statistics_text: str
    autotrace_text: str
    duration_ms: float
    metadata: ExecutionMetadata


@dataclass(frozen=True, slots=True, kw_only=True)
class BenchmarkResult:
    """Repeated execution timings in milliseconds."""

    metadata: ExecutionMetadata
    samples_ms: tuple[float, ...]
    iterations: int = 0
    warmup_iterations: int = 0
    minimum_ms: float = 0.0
    maximum_ms: float = 0.0
    average_ms: float = 0.0
    median_ms: float = 0.0


@dataclass(frozen=True, slots=True, kw_only=True)
class ComparisonDifference:
    """A secret-free description of one comparison mismatch."""

    kind: ComparisonDifferenceKind
    location: ComparisonLocation
    key_values: tuple[DatabaseValue, ...] | None = None
    row_index: int | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class CompareSideSummary:
    """Shape of one compared side without echoing full row payloads."""

    columns: tuple[ColumnDefinition, ...]
    row_count: int
    truncated: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class CompareResult:
    """Presentation-neutral comparison outcome."""

    equal: bool
    left: CompareSideSummary
    right: CompareSideSummary
    differences: tuple[ComparisonDifference, ...] = ()
    metadata: ExecutionMetadata | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class InspectionResult:
    """Typed result for one read-only server or schema inspection."""

    kind: InspectionKind
    query: QueryResult


CapabilityValue: TypeAlias = JsonScalar | list[str]


@dataclass(frozen=True, slots=True, kw_only=True)
class ServerInfo:
    """Identity, build and runtime state of the connected DM server."""

    name: str
    instance_name: str
    host_name: str
    version: str
    db_version: str
    build_version: str
    build_time: str
    start_time: str | None
    status: str
    mode: str


@dataclass(frozen=True, slots=True, kw_only=True)
class SessionInfo:
    """The authenticated user and default schema of one session."""

    user: str
    schema: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ServerInspectResult:
    """Server and session identity returned by ``server inspect``."""

    server: ServerInfo
    session: SessionInfo
    metadata: ExecutionMetadata


@dataclass(frozen=True, slots=True, kw_only=True)
class CapabilityFact:
    """One typed server capability value and the source it was read from."""

    name: str
    value: CapabilityValue
    source: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ServerCapabilitiesResult:
    """Typed capability facts returned by ``server capabilities``."""

    facts: tuple[CapabilityFact, ...]
    metadata: ExecutionMetadata


@dataclass(frozen=True, slots=True, kw_only=True)
class DescribeResult:
    """Column catalog rows plus the table comment for one table."""

    query: QueryResult
    table_comment: str | None


InspectionResponse: TypeAlias = InspectionResult | ServerInspectResult | ServerCapabilitiesResult | DescribeResult


@dataclass(frozen=True, slots=True, kw_only=True)
class DdlResult:
    """DDL text returned by the DM metadata package."""

    object_type: ObjectType
    schema: str | None
    name: str
    ddl: str
    metadata: ExecutionMetadata


@dataclass(frozen=True, slots=True, kw_only=True)
class AnalyzeOptions:
    """Explicit DBMS_STATS options used by one table analysis."""

    estimate_percent: float | None = None
    cascade: bool = False
    degree: int | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class AnalyzeStatistics:
    """Statistics snapshot captured before or after one table analysis."""

    last_analyzed: datetime | None = None
    num_rows: int | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class AnalyzeResult:
    """Result of one table-level DBMS_STATS operation."""

    schema: str
    table: str
    partition: str | None
    options: AnalyzeOptions
    before: AnalyzeStatistics
    after: AnalyzeStatistics
    outcome: WriteOutcome
    duration_ms: float
    metadata: ExecutionMetadata


ResponsePayload: TypeAlias = (
    QueryResult
    | WriteResult
    | ExplainResult
    | ActualPlanResult
    | BenchmarkResult
    | CompareResult
    | InspectionResponse
    | DdlResult
    | AnalyzeResult
)


__all__ = [
    "PLAN_FIRST_LINE_INDENT",
    "PLAN_FORMAT_TEXT",
    "ActualPlanResult",
    "AnalyzeOptions",
    "AnalyzeResult",
    "AnalyzeStatistics",
    "BenchmarkResult",
    "CapabilityFact",
    "CapabilityValue",
    "ColumnDefinition",
    "CompareResult",
    "CompareSideSummary",
    "ComparisonDifference",
    "DatabaseRow",
    "DdlResult",
    "DescribeResult",
    "ExecutionMetadata",
    "ExplainResult",
    "InspectionResponse",
    "InspectionResult",
    "PlanNode",
    "PlanStatistic",
    "QueryResult",
    "ResponsePayload",
    "ServerCapabilitiesResult",
    "ServerInfo",
    "ServerInspectResult",
    "SessionInfo",
    "TargetMetadata",
    "WriteResult",
]
