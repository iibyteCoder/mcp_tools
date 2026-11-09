"""Read-only schema catalog inspection over one DM connection."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Final

from dm_client.domain.enums import InspectionKind, SqlStatementType
from dm_client.domain.errors import ObjectNotFoundError
from dm_client.domain.results import (
    ColumnDefinition,
    DescribeResult,
    InspectionResult,
    QueryResult,
    TargetMetadata,
)
from dm_client.execution.inspection_support import (
    database_rows,
    effective_schema,
    fetch_all,
    resolve_target,
    text_value,
)
from dm_client.execution.tabular import (
    DEFAULT_MAX_BYTES,
    DEFAULT_MAX_ROWS,
    build_metadata,
    build_query_result,
)
from dm_client.sql.inspection_queries import (
    SCHEMA_COLUMNS_QUERY,
    SCHEMA_DATABASES_QUERY,
    SCHEMA_INDEXES_QUERY,
    SCHEMA_TABLE_COMMENT_QUERY,
    SCHEMA_TABLES_QUERY,
    build_schema_stats_query,
)

if TYPE_CHECKING:
    from dm_client.domain.requests import (
        SchemaDatabasesRequest,
        SchemaDescribeRequest,
        SchemaIndexesRequest,
        SchemaStatsRequest,
        SchemaTablesRequest,
    )
    from dm_client.domain.values import DatabaseParameters
    from dm_client.ports.driver import DmConnection, DmCursor

_DATABASE_COLUMNS: Final[tuple[ColumnDefinition, ...]] = (
    ColumnDefinition(name="SCHEMA_NAME", type_name="VARCHAR", nullable=False, ordinal=0),
    ColumnDefinition(name="USER_ID", type_name="NUMBER", nullable=False, ordinal=1),
    ColumnDefinition(name="IS_SYSTEM", type_name="BOOLEAN", nullable=False, ordinal=2),
)


def run_schema_databases(
    connection: DmConnection,
    request: SchemaDatabasesRequest,
    target_label: str,
    target: TargetMetadata | None,
) -> InspectionResult:
    """Read visible schemas, hiding system schemas unless requested."""

    started_at = datetime.now(timezone.utc)
    resolved_target = resolve_target(connection, target_label, target)
    cursor = connection.cursor()
    try:
        cursor.execute(SCHEMA_DATABASES_QUERY)
        raw_rows = fetch_all(cursor)
    finally:
        cursor.close()

    rows = database_rows(raw_rows, include_all=request.include_all)
    metadata = build_metadata(SqlStatementType.SELECT, started_at, resolved_target, row_count=len(rows))
    query = QueryResult(columns=_DATABASE_COLUMNS, rows=rows, metadata=metadata)
    return InspectionResult(kind=InspectionKind.SCHEMA_DATABASES, query=query)


def run_schema_tables(
    connection: DmConnection,
    request: SchemaTablesRequest,
    target_label: str,
    target: TargetMetadata | None,
) -> InspectionResult:
    """Read tables in the selected or explicitly named schema."""

    schema = effective_schema(connection, request.schema)
    return _tabular_inspection(
        connection,
        kind=InspectionKind.SCHEMA_TABLES,
        sql=SCHEMA_TABLES_QUERY,
        parameters=(schema,),
        target_label=target_label,
        target=target,
    )


def run_schema_indexes(
    connection: DmConnection,
    request: SchemaIndexesRequest,
    target_label: str,
    target: TargetMetadata | None,
) -> InspectionResult:
    """Read one row per index column of one table."""

    schema = effective_schema(connection, request.schema)
    return _tabular_inspection(
        connection,
        kind=InspectionKind.SCHEMA_INDEXES,
        sql=SCHEMA_INDEXES_QUERY,
        parameters=(schema, request.table.value),
        target_label=target_label,
        target=target,
    )


def run_schema_stats(
    connection: DmConnection,
    request: SchemaStatsRequest,
    target_label: str,
    target: TargetMetadata | None,
) -> InspectionResult:
    """Read table statistics for the schema with an optional table filter."""

    schema = effective_schema(connection, request.schema)
    table = request.table.value if request.table is not None else None
    return _tabular_inspection(
        connection,
        kind=InspectionKind.SCHEMA_STATS,
        sql=build_schema_stats_query(table_filtered=table is not None),
        parameters=(schema,) if table is None else (schema, table),
        target_label=target_label,
        target=target,
    )


def run_schema_describe(
    connection: DmConnection,
    request: SchemaDescribeRequest,
    target_label: str,
    target: TargetMetadata | None,
) -> DescribeResult:
    """Read columns and the table comment of one table."""

    started_at = datetime.now(timezone.utc)
    resolved_target = resolve_target(connection, target_label, target)
    schema = effective_schema(connection, request.schema)
    table = request.table.value
    cursor = connection.cursor()
    try:
        cursor.execute(SCHEMA_COLUMNS_QUERY, (schema, table))
        query = build_query_result(
            cursor,
            build_metadata(SqlStatementType.SELECT, started_at, resolved_target),
            DEFAULT_MAX_ROWS,
            DEFAULT_MAX_BYTES,
        )
        if not query.rows:
            raise ObjectNotFoundError(
                f"table {schema}.{table} was not found",
                hint="verify the schema and table name and that the user can read them",
            )
        table_comment = _table_comment(cursor, schema, table)
    finally:
        cursor.close()
    return DescribeResult(query=query, table_comment=table_comment)


def _tabular_inspection(
    connection: DmConnection,
    *,
    kind: InspectionKind,
    sql: str,
    parameters: DatabaseParameters,
    target_label: str,
    target: TargetMetadata | None,
) -> InspectionResult:
    started_at = datetime.now(timezone.utc)
    resolved_target = resolve_target(connection, target_label, target)
    cursor = connection.cursor()
    try:
        cursor.execute(sql, parameters)
        query = build_query_result(
            cursor,
            build_metadata(SqlStatementType.SELECT, started_at, resolved_target),
            DEFAULT_MAX_ROWS,
            DEFAULT_MAX_BYTES,
        )
    finally:
        cursor.close()
    return InspectionResult(kind=kind, query=query)


def _table_comment(cursor: DmCursor, schema: str, table: str) -> str | None:
    cursor.execute(SCHEMA_TABLE_COMMENT_QUERY, (schema, table))
    rows = fetch_all(cursor)
    if not rows or not rows[0] or rows[0][0] is None:
        return None
    return text_value(rows[0][0])


__all__ = [
    "run_schema_databases",
    "run_schema_describe",
    "run_schema_indexes",
    "run_schema_stats",
    "run_schema_tables",
]
