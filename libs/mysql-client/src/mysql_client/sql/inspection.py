"""Central read-only SQL definitions for server and schema inspection."""

from __future__ import annotations

from dataclasses import dataclass

from mysql_client.domain.enums import InspectionCommand, SqlStatementType
from mysql_client.domain.requests import (
    InspectionRequest,
    SchemaDatabasesRequest,
    SchemaDescribeRequest,
    SchemaIndexesRequest,
    SchemaStatsRequest,
    SchemaTablesRequest,
    ServerCapabilitiesRequest,
    ServerInspectRequest,
)
from mysql_client.domain.values import DatabaseName, DatabaseValue, SqlText

SERVER_INSPECT_SQL = SqlText(
    "SELECT VERSION() AS server_version, @@version_comment AS version_comment, "
    "@@hostname AS hostname, @@port AS server_port, DATABASE() AS current_database, "
    "CURRENT_USER() AS current_user, @@character_set_server AS character_set_server, "
    "@@collation_server AS collation_server"
)
SERVER_CAPABILITIES_SQL = SqlText(
    "SELECT @@version AS server_version, @@transaction_isolation AS transaction_isolation, "
    "@@autocommit AS autocommit, @@performance_schema AS performance_schema, "
    "@@have_ssl AS have_ssl, @@sql_mode AS sql_mode"
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


def _database_value(database: DatabaseName | None) -> DatabaseValue:
    if database is None:
        return None
    return database.value


__all__ = [
    "SCHEMA_DATABASES_SQL",
    "SCHEMA_DESCRIBE_SQL",
    "SCHEMA_INDEXES_SQL",
    "SCHEMA_STATS_SQL",
    "SCHEMA_TABLES_SQL",
    "SERVER_CAPABILITIES_SQL",
    "SERVER_INSPECT_SQL",
    "InspectionQueryDefinition",
    "build_inspection_query",
]
