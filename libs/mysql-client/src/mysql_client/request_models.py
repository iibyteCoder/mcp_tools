"""Immutable requests and execution policies for the MySQL client domain."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, TypeAlias

from mysql_client.enums import ExplainFormat, InputSource, SqlStatementType, TransactionAction
from mysql_client.value_models import DatabaseValue, SqlText

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True, slots=True, kw_only=True)
class SqlInput:
    """SQL text plus provenance, without performing external I/O."""

    text: SqlText
    source: InputSource = InputSource.INLINE
    name: str | None = None

    def __post_init__(self) -> None:
        return None

    @classmethod
    def inline(cls, text: str) -> SqlInput:
        return cls(text=SqlText(text), source=InputSource.INLINE)

    @classmethod
    def file(cls, text: str, path: str | Path) -> SqlInput:
        return cls(text=SqlText(text), source=InputSource.FILE, name=str(path))

    @classmethod
    def stdin(cls, text: str) -> SqlInput:
        return cls(text=SqlText(text), source=InputSource.STDIN, name="<stdin>")


@dataclass(frozen=True, slots=True, kw_only=True)
class ParsedSql:
    """Parser output used by the execution layer."""

    original_sql: SqlText = field(repr=False)
    normalized_sql: SqlText = field(repr=False)
    statement_type: SqlStatementType
    is_read_only: bool
    is_write: bool
    requires_explicit_transaction: bool
    is_explain_analyze: bool = False

    def __post_init__(self) -> None:
        if not self.original_sql.strip():
            raise ValueError("原始 SQL 不能为空")
        if not self.normalized_sql.strip():
            raise ValueError("规范化 SQL 不能为空")
        if self.statement_type is SqlStatementType.UNKNOWN:
            raise ValueError("ParsedSql 不能使用 UNKNOWN 语句类型")
        if self.is_read_only == self.is_write:
            raise ValueError("ParsedSql 必须明确表示只读或写入语句")
        if self.is_explain_analyze and self.statement_type is not SqlStatementType.EXPLAIN:
            raise ValueError("只有 EXPLAIN 语句可以标记为 ANALYZE")


@dataclass(frozen=True, slots=True, kw_only=True)
class ReadRequest:
    """Request for a read whose SQL is executed without rewriting."""

    sql: SqlInput
    parameters: tuple[DatabaseValue, ...] = ()
    max_rows: int | None = None
    max_bytes: int | None = None
    statement_timeout_seconds: float | None = None
    statement_type: SqlStatementType = SqlStatementType.SELECT

    def __post_init__(self) -> None:
        if self.max_rows is not None and self.max_rows < 1:
            raise ValueError("最大行数必须大于 0")
        if self.max_bytes is not None and self.max_bytes < 1:
            raise ValueError("最大字节数必须大于 0")
        if self.statement_timeout_seconds is not None and self.statement_timeout_seconds <= 0:
            raise ValueError("语句超时必须大于 0")


@dataclass(frozen=True, slots=True, kw_only=True)
class WriteRequest:
    """Request for one explicitly authorized write or DDL statement."""

    sql: SqlInput
    parameters: tuple[DatabaseValue, ...] = ()
    statement_type: SqlStatementType = SqlStatementType.UNKNOWN
    transaction: TransactionAction = TransactionAction.COMMIT
    statement_timeout_seconds: float | None = None

    def __post_init__(self) -> None:
        if self.statement_timeout_seconds is not None and self.statement_timeout_seconds <= 0:
            raise ValueError("语句超时必须大于 0")


@dataclass(frozen=True, slots=True, kw_only=True)
class ExplainRequest:
    """Request for an execution plan."""

    sql: SqlInput
    parameters: tuple[DatabaseValue, ...] = ()
    format: ExplainFormat = ExplainFormat.TRADITIONAL
    analyze: bool = False
    statement_timeout_seconds: float | None = None

    def __post_init__(self) -> None:
        if self.statement_timeout_seconds is not None and self.statement_timeout_seconds <= 0:
            raise ValueError("语句超时必须大于 0")


@dataclass(frozen=True, slots=True, kw_only=True)
class BenchmarkRequest:
    """Request for repeated execution measurements."""

    sql: SqlInput
    parameters: tuple[DatabaseValue, ...] = ()
    iterations: int | None = None
    warmup_iterations: int | None = None
    statement_timeout_seconds: float | None = None

    def __post_init__(self) -> None:
        if self.iterations is not None and self.iterations < 1:
            raise ValueError("benchmark 至少需要一次迭代")
        if self.warmup_iterations is not None and self.warmup_iterations < 0:
            raise ValueError("预热迭代次数不能为负数")
        if self.statement_timeout_seconds is not None and self.statement_timeout_seconds <= 0:
            raise ValueError("语句超时必须大于 0")


@dataclass(frozen=True, slots=True, kw_only=True)
class CompareRequest:
    """Request to compare two SQL inputs in an execution context."""

    left_sql: SqlInput
    right_sql: SqlInput
    left_parameters: tuple[DatabaseValue, ...] = ()
    right_parameters: tuple[DatabaseValue, ...] = ()
    key_columns: tuple[str, ...] = ()
    max_diff_samples: int | None = None
    statement_timeout_seconds: float | None = None

    def __post_init__(self) -> None:
        if self.max_diff_samples is not None and self.max_diff_samples < 0:
            raise ValueError("差异样本数不能为负数")
        if self.statement_timeout_seconds is not None and self.statement_timeout_seconds <= 0:
            raise ValueError("语句超时必须大于 0")


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionPolicyDefaults:
    """Typed default limits for client execution, independent of CLI policy."""

    max_rows: int = 10_000
    max_bytes: int = 1_048_576
    statement_timeout_seconds: float = 30.0
    benchmark_iterations: int = 10
    benchmark_warmup_iterations: int = 1
    max_diff_samples: int = 20

    def __post_init__(self) -> None:
        if self.max_rows < 1 or self.max_bytes < 1:
            raise ValueError("结果限制必须大于 0")
        if self.statement_timeout_seconds <= 0:
            raise ValueError("语句超时必须大于 0")
        if self.benchmark_iterations < 1 or self.benchmark_warmup_iterations < 0:
            raise ValueError("benchmark 默认值无效")
        if self.max_diff_samples < 0:
            raise ValueError("差异样本数不能为负数")


Request: TypeAlias = ReadRequest | WriteRequest | ExplainRequest | BenchmarkRequest | CompareRequest
