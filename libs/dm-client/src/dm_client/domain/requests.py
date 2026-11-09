"""Immutable typed requests for the Dameng client domain."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypeAlias

from dm_client.domain.enums import ObjectType, SqlReadEffect, SqlStatementType, TransactionAction
from dm_client.domain.values import (
    DatabaseParameters,
    ObjectName,
    SchemaName,
    SqlText,
    TableName,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class SqlInput:
    """SQL text with an optional provenance label, without performing I/O."""

    text: SqlText
    name: str | None = None

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("SQL text must not be empty")

    @classmethod
    def inline(cls, text: str) -> SqlInput:
        """Build an inline SQL input."""

        return cls(text=SqlText(text))


@dataclass(frozen=True, slots=True, kw_only=True)
class ParsedSql:
    """Local parser output consumed by policy checks and execution."""

    original_sql: SqlText = field(repr=False)
    normalized_sql: SqlText = field(repr=False)
    statement_type: SqlStatementType
    is_read_only: bool
    is_write: bool
    requires_explicit_transaction: bool
    is_explain_analyze: bool = False
    read_effect: SqlReadEffect = SqlReadEffect.NONE

    def __post_init__(self) -> None:
        if not self.original_sql.strip():
            raise ValueError("original SQL must not be empty")
        if not self.normalized_sql.strip():
            raise ValueError("normalized SQL must not be empty")
        if self.is_read_only and self.is_write:
            raise ValueError("parsed SQL cannot be both read-only and write")


@dataclass(frozen=True, slots=True, kw_only=True)
class ReadRequest:
    """Request for one bounded read executed without rewriting its SQL."""

    sql: SqlInput
    parameters: DatabaseParameters = ()
    max_rows: int | None = None
    max_bytes: int | None = None
    statement_timeout_seconds: float | None = None

    def __post_init__(self) -> None:
        if self.max_rows is not None and self.max_rows < 1:
            raise ValueError("max rows must be greater than zero")
        if self.max_bytes is not None and self.max_bytes < 1:
            raise ValueError("max bytes must be greater than zero")
        _validate_optional_timeout(self.statement_timeout_seconds)


@dataclass(frozen=True, slots=True, kw_only=True)
class WriteRequest:
    """Request for one explicitly authorized write or DDL statement."""

    sql: SqlInput
    parameters: DatabaseParameters = ()
    statement_type: SqlStatementType = SqlStatementType.OTHER
    transaction: TransactionAction = TransactionAction.COMMIT
    statement_timeout_seconds: float | None = None

    def __post_init__(self) -> None:
        _validate_optional_timeout(self.statement_timeout_seconds)


@dataclass(frozen=True, slots=True, kw_only=True)
class ExplainRequest:
    """Request for one text execution plan; parameters are not supported."""

    sql: SqlInput
    statement_timeout_seconds: float | None = None

    def __post_init__(self) -> None:
        _validate_optional_timeout(self.statement_timeout_seconds)


@dataclass(frozen=True, slots=True, kw_only=True)
class BenchmarkRequest:
    """Request for repeated read-only execution measurements."""

    sql: SqlInput
    parameters: DatabaseParameters = ()
    iterations: int | None = None
    warmup_iterations: int | None = None
    statement_timeout_seconds: float | None = None

    def __post_init__(self) -> None:
        if self.iterations is not None and self.iterations < 1:
            raise ValueError("benchmark requires at least one iteration")
        if self.warmup_iterations is not None and self.warmup_iterations < 0:
            raise ValueError("warmup iterations must not be negative")
        _validate_optional_timeout(self.statement_timeout_seconds)


@dataclass(frozen=True, slots=True, kw_only=True)
class CompareRequest:
    """Request to compare two read-only SQL inputs."""

    left_sql: SqlInput
    right_sql: SqlInput
    left_parameters: DatabaseParameters = ()
    right_parameters: DatabaseParameters = ()
    key_columns: tuple[str, ...] = ()
    max_diff_samples: int | None = None
    statement_timeout_seconds: float | None = None

    def __post_init__(self) -> None:
        if self.max_diff_samples is not None and self.max_diff_samples < 0:
            raise ValueError("difference sample count must not be negative")
        _validate_optional_timeout(self.statement_timeout_seconds)


@dataclass(frozen=True, slots=True, kw_only=True)
class ServerInspectRequest:
    """Request for read-only server identity and session details."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ServerCapabilitiesRequest:
    """Request for typed server capability facts."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ServerParametersRequest:
    """Request for DM server parameters."""

    name_filter: str | None = None
    include_all: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class SchemaDatabasesRequest:
    """Request for visible DM schemas."""

    include_all: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class SchemaTablesRequest:
    """Request for tables in the selected or explicitly named schema."""

    schema: SchemaName | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class SchemaDescribeRequest:
    """Request for columns of one table."""

    table: TableName
    schema: SchemaName | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class SchemaIndexesRequest:
    """Request for indexes of one table."""

    table: TableName
    schema: SchemaName | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class SchemaStatsRequest:
    """Request for table statistics in the selected or named schema."""

    table: TableName | None = None
    schema: SchemaName | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class SchemaConstraintsRequest:
    """Request for constraints in the selected or named schema."""

    table: TableName | None = None
    schema: SchemaName | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class SchemaObjectsRequest:
    """Request for catalog objects in the selected or named schema."""

    object_type: ObjectType | None = None
    schema: SchemaName | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class SchemaDdlRequest:
    """Request for generated DDL of one catalog object."""

    object_type: ObjectType
    name: ObjectName
    schema: SchemaName | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class SchemaAnalyzeRequest:
    """Request for one table-level DBMS_STATS operation."""

    table: TableName
    schema: SchemaName | None = None
    partition: str | None = None
    estimate_percent: float | None = None
    cascade: bool = True
    degree: int | None = None

    def __post_init__(self) -> None:
        if self.partition is not None and not self.partition.strip():
            raise ValueError("partition name must not be empty")
        if self.estimate_percent is not None and not 0 < self.estimate_percent <= 100:
            raise ValueError("estimate percent must be greater than zero and at most 100")
        if self.degree is not None and self.degree < 1:
            raise ValueError("degree must be at least one")


InspectionRequest: TypeAlias = (
    ServerInspectRequest
    | ServerCapabilitiesRequest
    | ServerParametersRequest
    | SchemaDatabasesRequest
    | SchemaTablesRequest
    | SchemaDescribeRequest
    | SchemaIndexesRequest
    | SchemaStatsRequest
    | SchemaConstraintsRequest
    | SchemaObjectsRequest
)
CatalogRequest: TypeAlias = SchemaDdlRequest
MaintenanceRequest: TypeAlias = SchemaAnalyzeRequest
Request: TypeAlias = (
    ReadRequest
    | WriteRequest
    | ExplainRequest
    | BenchmarkRequest
    | CompareRequest
    | InspectionRequest
    | CatalogRequest
    | MaintenanceRequest
)


def _validate_optional_timeout(seconds: float | None) -> None:
    if seconds is not None and seconds <= 0:
        raise ValueError("statement timeout must be greater than zero")


__all__ = [
    "BenchmarkRequest",
    "CatalogRequest",
    "CompareRequest",
    "ExplainRequest",
    "InspectionRequest",
    "MaintenanceRequest",
    "ParsedSql",
    "ReadRequest",
    "Request",
    "SchemaAnalyzeRequest",
    "SchemaConstraintsRequest",
    "SchemaDatabasesRequest",
    "SchemaDdlRequest",
    "SchemaDescribeRequest",
    "SchemaIndexesRequest",
    "SchemaObjectsRequest",
    "SchemaStatsRequest",
    "SchemaTablesRequest",
    "ServerCapabilitiesRequest",
    "ServerInspectRequest",
    "ServerParametersRequest",
    "SqlInput",
    "WriteRequest",
]
