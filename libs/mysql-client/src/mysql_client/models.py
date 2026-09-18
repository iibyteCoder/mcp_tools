"""Immutable, JSON-safe boundary models for the MySQL Agent CLI."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING, TypeAlias

from mysql_client.enums import (
    ErrorCode,
    ExitCode,
    ExplainFormat,
    InputSource,
    OutputFormat,
    ResponseStatus,
    SqlStatementType,
)

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path


JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
DatabaseScalar: TypeAlias = JsonScalar | bytes | Decimal | date | datetime | time
DatabaseValue: TypeAlias = DatabaseScalar | list["DatabaseValue"] | dict[str, "DatabaseValue"]


@dataclass(frozen=True, slots=True, kw_only=True)
class SqlInput:
    """SQL text plus its provenance, without reading from external systems."""

    text: str
    source: InputSource = InputSource.INLINE
    name: str | None = None

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("SQL 输入不能为空")

    @classmethod
    def inline(cls, text: str) -> SqlInput:
        return cls(text=text, source=InputSource.INLINE)

    @classmethod
    def file(cls, text: str, path: str | Path) -> SqlInput:
        return cls(text=text, source=InputSource.FILE, name=str(path))

    @classmethod
    def stdin(cls, text: str) -> SqlInput:
        return cls(text=text, source=InputSource.STDIN, name="<stdin>")


@dataclass(frozen=True, slots=True, kw_only=True)
class ParsedSql:
    """Parser output used by the execution layer."""

    text: str
    statement_type: SqlStatementType


@dataclass(frozen=True, slots=True, kw_only=True)
class ReadRequest:
    """Request for a bounded read operation."""

    sql: SqlInput
    parameters: tuple[DatabaseValue, ...] = ()
    page: int = 1
    page_size: int = 100

    def __post_init__(self) -> None:
        if self.page < 1:
            raise ValueError("页码必须大于等于 1")
        if self.page_size < 1:
            raise ValueError("分页大小必须大于 0")


@dataclass(frozen=True, slots=True, kw_only=True)
class WriteRequest:
    """Request for an authorized write or DDL operation."""

    sql: SqlInput
    parameters: tuple[DatabaseValue, ...] = ()
    statement_type: SqlStatementType = SqlStatementType.UNKNOWN


@dataclass(frozen=True, slots=True, kw_only=True)
class ExplainRequest:
    """Request for an execution plan."""

    sql: SqlInput
    parameters: tuple[DatabaseValue, ...] = ()
    format: ExplainFormat = ExplainFormat.TRADITIONAL
    analyze: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class BenchmarkRequest:
    """Request for repeated execution measurements."""

    sql: SqlInput
    parameters: tuple[DatabaseValue, ...] = ()
    iterations: int = 10
    warmup_iterations: int = 1

    def __post_init__(self) -> None:
        if self.iterations < 1:
            raise ValueError("benchmark 至少需要一次迭代")
        if self.warmup_iterations < 0:
            raise ValueError("预热迭代次数不能为负数")


@dataclass(frozen=True, slots=True, kw_only=True)
class TargetMetadata:
    """Secret-free identity and server details for an execution target."""

    label: str
    host: str | None = None
    port: int | None = None
    database: str | None = None
    server_version: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class CompareRequest:
    """Request to compare the same SQL against two targets."""

    sql: SqlInput
    left_target: TargetMetadata
    right_target: TargetMetadata
    parameters: tuple[DatabaseValue, ...] = ()
    iterations: int = 1

    def __post_init__(self) -> None:
        if self.iterations < 1:
            raise ValueError("比较至少需要一次迭代")


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
    """Named row payload; values retain database-native scalar values."""

    values: tuple[DatabaseValue, ...]

    @classmethod
    def from_values(cls, values: Iterable[DatabaseValue]) -> DatabaseRow:
        return cls(values=tuple(values))


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionMetadata:
    """Measurements and target identity attached to a result."""

    statement_type: SqlStatementType
    duration_ms: float
    row_count: int = 0
    affected_rows: int = 0
    target: TargetMetadata | None = None
    started_at: datetime | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class QueryResult:
    """Tabular read result with explicit pagination state."""

    columns: tuple[ColumnDefinition, ...]
    rows: tuple[DatabaseRow, ...]
    metadata: ExecutionMetadata
    has_more: bool = False
    next_page: int | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class WriteResult:
    """Result of a write or DDL operation."""

    affected_rows: int
    metadata: ExecutionMetadata
    generated_values: tuple[DatabaseValue, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class ExplainResult:
    """Execution plan represented as a regular tabular result."""

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
    """Comparison outcome with explicit, presentation-neutral differences."""

    equal: bool
    left: QueryResult
    right: QueryResult
    differences: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class ErrorReport:
    """Stable structured error payload."""

    code: ErrorCode
    message: str
    exit_code: ExitCode = ExitCode.INTERNAL_ERROR
    hint: str | None = None
    exception_type: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class CliResponse:
    """Presentation boundary shared by CLI commands and agents."""

    status: ResponseStatus
    exit_code: ExitCode
    output_format: OutputFormat
    payload: QueryResult | WriteResult | ExplainResult | BenchmarkResult | CompareResult | None = None
    error: ErrorReport | None = None

    @classmethod
    def success(
        cls,
        payload: QueryResult | WriteResult | ExplainResult | BenchmarkResult | CompareResult,
        *,
        output_format: OutputFormat = OutputFormat.TABLE,
    ) -> CliResponse:
        return cls(
            status=ResponseStatus.SUCCESS,
            exit_code=ExitCode.SUCCESS,
            output_format=output_format,
            payload=payload,
        )

    @classmethod
    def failure(cls, error: ErrorReport, *, output_format: OutputFormat = OutputFormat.TABLE) -> CliResponse:
        return cls(
            status=ResponseStatus.ERROR,
            exit_code=error.exit_code,
            output_format=output_format,
            error=error,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionPolicyDefaults:
    """Centralized execution limits used by later command implementations."""

    page_size: int = 100
    max_page_size: int = 1_000
    max_rows: int = 10_000
    benchmark_iterations: int = 10
    benchmark_warmup_iterations: int = 1
    max_compare_rows: int = 10_000
    statement_timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        if self.page_size < 1 or self.max_page_size < self.page_size:
            raise ValueError("分页默认值无效")
        if self.max_rows < 1 or self.max_compare_rows < 1:
            raise ValueError("结果行数限制必须大于 0")
        if self.benchmark_iterations < 1 or self.benchmark_warmup_iterations < 0:
            raise ValueError("benchmark 默认值无效")
        if self.statement_timeout_seconds <= 0:
            raise ValueError("语句超时必须大于 0")


class CancellationReason(str, Enum):
    """Reasons supplied to a cancellation controller."""

    USER_REQUEST = "user_request"
    SHUTDOWN = "shutdown"
    POLICY = "policy"


Request: TypeAlias = ReadRequest | WriteRequest | ExplainRequest | BenchmarkRequest | CompareRequest
ResponsePayload: TypeAlias = QueryResult | WriteResult | ExplainResult | BenchmarkResult | CompareResult
