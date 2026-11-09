"""Central read-only SQL definitions for server and schema inspection."""

from __future__ import annotations

import re
from dataclasses import dataclass

from mysql_client.domain.enums import InspectionCommand, ServerMetricKind, SqlStatementType
from mysql_client.domain.requests import (
    InspectionRequest,
    SchemaDatabasesRequest,
    SchemaDescribeRequest,
    SchemaIndexesRequest,
    SchemaStatsRequest,
    SchemaTablesRequest,
    ServerCapabilitiesRequest,
    ServerInspectRequest,
    ServerMetricsRequest,
    ServerProcessesRequest,
)
from mysql_client.domain.values import DatabaseName, DatabaseValue, SqlText

SERVER_INSPECT_SQL = SqlText(
    "SELECT VERSION() AS server_version, @@version_comment AS version_comment, "
    "@@hostname AS hostname, @@port AS server_port, DATABASE() AS current_database, "
    "CURRENT_USER() AS `current_user`, @@character_set_server AS character_set_server, "
    "@@collation_server AS collation_server"
)
SERVER_CAPABILITIES_SQL = SqlText(
    "SELECT @@version AS server_version, @@transaction_isolation AS transaction_isolation, "
    "@@autocommit AS autocommit, @@performance_schema AS performance_schema, "
    "@@have_ssl AS have_ssl, @@sql_mode AS sql_mode"
)
SERVER_PROCESSES_SQL = SqlText(
    "SELECT ID AS id, USER AS user, HOST AS host, DB AS `database`, COMMAND AS command, "
    "TIME AS time_seconds, STATE AS state, "
    "CASE WHEN %s THEN INFO ELSE NULL END AS info "
    "FROM performance_schema.processlist ORDER BY ID"
)
SCHEMA_DATABASES_SQL = SqlText(
    "SELECT SCHEMA_NAME AS database_name, DEFAULT_CHARACTER_SET_NAME AS default_character_set, "
    "DEFAULT_COLLATION_NAME AS default_collation "
    "FROM information_schema.SCHEMATA ORDER BY SCHEMA_NAME"
)
SCHEMA_TABLES_SQL = SqlText(
    "SELECT TABLE_SCHEMA AS database_name, TABLE_NAME AS table_name, TABLE_TYPE AS table_type, "
    "ENGINE AS engine, TABLE_ROWS AS estimated_rows "
    "FROM information_schema.TABLES "
    "WHERE TABLE_SCHEMA = COALESCE(%s, DATABASE()) ORDER BY TABLE_NAME"
)
SCHEMA_DESCRIBE_SQL = SqlText(
    "SELECT TABLE_SCHEMA AS database_name, TABLE_NAME AS table_name, ORDINAL_POSITION AS ordinal_position, "
    "COLUMN_NAME AS column_name, COLUMN_TYPE AS column_type, IS_NULLABLE AS is_nullable, "
    "COLUMN_DEFAULT AS column_default, EXTRA AS extra, COLUMN_COMMENT AS column_comment "
    "FROM information_schema.COLUMNS "
    "WHERE TABLE_SCHEMA = COALESCE(%s, DATABASE()) AND TABLE_NAME = %s "
    "ORDER BY ORDINAL_POSITION"
)
SCHEMA_INDEXES_SQL = SqlText(
    "SELECT TABLE_SCHEMA AS database_name, TABLE_NAME AS table_name, INDEX_NAME AS index_name, "
    "NON_UNIQUE AS non_unique, SEQ_IN_INDEX AS sequence_in_index, COLUMN_NAME AS column_name, "
    "COLLATION AS collation, CARDINALITY AS cardinality, SUB_PART AS sub_part, "
    "INDEX_TYPE AS index_type, INDEX_COMMENT AS index_comment "
    "FROM information_schema.STATISTICS "
    "WHERE TABLE_SCHEMA = COALESCE(%s, DATABASE()) AND TABLE_NAME = %s "
    "ORDER BY INDEX_NAME, SEQ_IN_INDEX"
)
SCHEMA_STATS_SQL = SqlText(
    "SELECT TABLE_SCHEMA AS database_name, TABLE_NAME AS table_name, ENGINE AS engine, "
    "TABLE_ROWS AS estimated_rows, AVG_ROW_LENGTH AS average_row_length, DATA_LENGTH AS data_length, "
    "MAX_DATA_LENGTH AS max_data_length, INDEX_LENGTH AS index_length, DATA_FREE AS data_free, "
    "CREATE_TIME AS create_time, UPDATE_TIME AS update_time, TABLE_COLLATION AS table_collation "
    "FROM information_schema.TABLES "
    "WHERE TABLE_SCHEMA = COALESCE(%s, DATABASE()) "
    "AND (%s IS NULL OR TABLE_NAME = %s) ORDER BY TABLE_NAME"
)

CURATED_SERVER_VARIABLE_NAMES: tuple[str, ...] = (
    "innodb_buffer_pool_instances",
    "innodb_buffer_pool_size",
    "innodb_flush_log_at_trx_commit",
    "innodb_flush_method",
    "innodb_io_capacity",
    "innodb_io_capacity_max",
    "innodb_log_buffer_size",
    "innodb_log_file_size",
    "innodb_read_io_threads",
    "innodb_thread_concurrency",
    "innodb_write_io_threads",
    "max_connections",
    "performance_schema",
    "sort_buffer_size",
    "table_open_cache",
    "thread_cache_size",
    "tmp_table_size",
    "transaction_isolation",
)
CURATED_SERVER_STATUS_NAMES: tuple[str, ...] = (
    "Aborted_clients",
    "Aborted_connects",
    "Connections",
    "Created_tmp_disk_tables",
    "Created_tmp_tables",
    "Innodb_buffer_pool_read_requests",
    "Innodb_buffer_pool_reads",
    "Innodb_buffer_pool_wait_free",
    "Innodb_row_lock_time_avg",
    "Innodb_row_lock_waits",
    "Max_used_connections",
    "Questions",
    "Select_full_join",
    "Select_scan",
    "Slow_queries",
    "Table_locks_waited",
    "Threads_connected",
    "Threads_running",
    "Uptime",
)
SENSITIVE_VARIABLE_MARKERS: tuple[str, ...] = (
    "password",
    "secret",
    "token",
    "private_key",
    "ssl_key",
)
SENSITIVE_VARIABLE_PATTERN = "|".join(re.escape(marker) for marker in SENSITIVE_VARIABLE_MARKERS)

# MySQL 8.0 removed INFORMATION_SCHEMA.GLOBAL_VARIABLES/GLOBAL_STATUS. The
# performance_schema tables expose the same VARIABLE_NAME/VARIABLE_VALUE shape.
_SERVER_VARIABLES_BASE_SQL = (
    "SELECT VARIABLE_NAME AS name, "
    "CASE WHEN LOWER(VARIABLE_NAME) REGEXP %s THEN NULL ELSE VARIABLE_VALUE END AS value, "
    "CASE WHEN LOWER(VARIABLE_NAME) REGEXP %s THEN 1 ELSE 0 END AS redacted "
    "FROM performance_schema.global_variables"
)
_SERVER_STATUS_BASE_SQL = (
    "SELECT VARIABLE_NAME AS name, VARIABLE_VALUE AS value FROM performance_schema.global_status"
)


@dataclass(frozen=True, slots=True, kw_only=True)
class InspectionQueryDefinition:
    """One trusted SQL statement and its bound values."""

    command: InspectionCommand
    sql: SqlText
    parameters: tuple[DatabaseValue, ...] = ()
    statement_type: SqlStatementType = SqlStatementType.SELECT


def build_inspection_query(request: InspectionRequest) -> InspectionQueryDefinition:
    """Build one read-only query from a typed inspection request."""

    if isinstance(request, ServerInspectRequest):
        return InspectionQueryDefinition(command=InspectionCommand.SERVER_INSPECT, sql=SERVER_INSPECT_SQL)
    if isinstance(request, ServerCapabilitiesRequest):
        return InspectionQueryDefinition(command=InspectionCommand.SERVER_CAPABILITIES, sql=SERVER_CAPABILITIES_SQL)
    if isinstance(request, ServerMetricsRequest):
        return _server_metrics_query(request)
    if isinstance(request, ServerProcessesRequest):
        return InspectionQueryDefinition(
            command=InspectionCommand.SERVER_PROCESSES,
            sql=SERVER_PROCESSES_SQL,
            parameters=(1 if request.include_sql else 0,),
        )
    if isinstance(request, SchemaDatabasesRequest):
        return InspectionQueryDefinition(command=InspectionCommand.SCHEMA_DATABASES, sql=SCHEMA_DATABASES_SQL)
    if isinstance(request, SchemaTablesRequest):
        return InspectionQueryDefinition(
            command=InspectionCommand.SCHEMA_TABLES,
            sql=SCHEMA_TABLES_SQL,
            parameters=(_database_value(request.database),),
        )
    if isinstance(request, SchemaDescribeRequest):
        return InspectionQueryDefinition(
            command=InspectionCommand.SCHEMA_DESCRIBE,
            sql=SCHEMA_DESCRIBE_SQL,
            parameters=(_database_value(request.database), request.table.value),
        )
    if isinstance(request, SchemaIndexesRequest):
        return InspectionQueryDefinition(
            command=InspectionCommand.SCHEMA_INDEXES,
            sql=SCHEMA_INDEXES_SQL,
            parameters=(_database_value(request.database), request.table.value),
        )
    if isinstance(request, SchemaStatsRequest):
        table = None if request.table is None else request.table.value
        return InspectionQueryDefinition(
            command=InspectionCommand.SCHEMA_STATS,
            sql=SCHEMA_STATS_SQL,
            parameters=(_database_value(request.database), table, table),
        )
    raise TypeError(f"不支持的 inspection 请求类型: {type(request).__name__}")


def _server_metrics_query(request: ServerMetricsRequest) -> InspectionQueryDefinition:
    if request.kind is ServerMetricKind.VARIABLES:
        command = InspectionCommand.SERVER_VARIABLES
        base_sql = _SERVER_VARIABLES_BASE_SQL
        base_parameters: tuple[DatabaseValue, ...] = (
            SENSITIVE_VARIABLE_PATTERN,
            SENSITIVE_VARIABLE_PATTERN,
        )
        curated_names: tuple[str, ...] = CURATED_SERVER_VARIABLE_NAMES
    elif request.kind is ServerMetricKind.STATUS:
        command = InspectionCommand.SERVER_STATUS
        base_sql = _SERVER_STATUS_BASE_SQL
        base_parameters = ()
        curated_names = CURATED_SERVER_STATUS_NAMES
    else:
        raise ValueError(f"不支持的 server metric 类型: {request.kind}")
    selected_names = None if request.filter_text is not None or request.all else curated_names
    name_predicate, name_parameters = _server_metric_name_predicate(
        curated_names=selected_names,
        filter_text=request.filter_text,
    )
    return InspectionQueryDefinition(
        command=command,
        sql=SqlText(f"{base_sql}{name_predicate} ORDER BY VARIABLE_NAME"),
        parameters=(*base_parameters, *name_parameters),
    )


def _server_metric_name_predicate(
    *,
    curated_names: tuple[str, ...] | None,
    filter_text: str | None,
) -> tuple[str, tuple[DatabaseValue, ...]]:
    if filter_text is not None:
        return " WHERE VARIABLE_NAME LIKE %s", (f"%{filter_text}%",)
    if curated_names is None:
        return "", ()
    placeholders = ", ".join("%s" for _ in curated_names)
    return f" WHERE VARIABLE_NAME IN ({placeholders})", tuple(curated_names)


def _database_value(database: DatabaseName | None) -> DatabaseValue:
    if database is None:
        return None
    return database.value


__all__ = [
    "CURATED_SERVER_STATUS_NAMES",
    "CURATED_SERVER_VARIABLE_NAMES",
    "SCHEMA_DATABASES_SQL",
    "SCHEMA_DESCRIBE_SQL",
    "SCHEMA_INDEXES_SQL",
    "SCHEMA_STATS_SQL",
    "SCHEMA_TABLES_SQL",
    "SENSITIVE_VARIABLE_MARKERS",
    "SENSITIVE_VARIABLE_PATTERN",
    "SERVER_CAPABILITIES_SQL",
    "SERVER_INSPECT_SQL",
    "SERVER_PROCESSES_SQL",
    "InspectionQueryDefinition",
    "build_inspection_query",
]
