"""Read-only SQL templates for server and schema inspection.

Every template reads DM catalog views without interpolating caller input; the
only dynamic fragments are qmark placeholder lists and optional clauses whose
bind values are supplied by the execution layer.
"""

from __future__ import annotations

from typing import Final

SERVER_INSTANCE_QUERY: Final[str] = (
    "SELECT NAME, INSTANCE_NAME, HOST_NAME, SVR_VERSION, DB_VERSION, START_TIME, "
    "STATUS$, MODE$, BUILD_VERSION, BUILD_TIME FROM V$INSTANCE"
)

SERVER_VERSIONS_QUERY: Final[str] = "SELECT BANNER FROM V$VERSION"

_SERVER_PARAMETER_COLUMNS: Final[str] = (
    "PARA_NAME, PARA_VALUE, SESS_VALUE, FILE_VALUE, DEFAULT_VALUE, MIN_VALUE, MAX_VALUE"
)

_SERVER_PARAMETERS_QUERY_TEMPLATE: Final[str] = (
    f"SELECT {_SERVER_PARAMETER_COLUMNS} FROM V$DM_INI "
    "WHERE PARA_NAME IN ({placeholders}) ORDER BY PARA_NAME"
)

SERVER_ALL_PARAMETERS_QUERY: Final[str] = (
    f"SELECT {_SERVER_PARAMETER_COLUMNS} FROM V$DM_INI ORDER BY PARA_NAME"
)

SERVER_FILTERED_PARAMETERS_QUERY: Final[str] = (
    f"SELECT {_SERVER_PARAMETER_COLUMNS} FROM V$DM_INI "
    "WHERE INSTR(UPPER(PARA_NAME), UPPER(?)) > 0 ORDER BY PARA_NAME"
)

SCHEMA_DATABASES_QUERY: Final[str] = "SELECT USERNAME, USER_ID FROM ALL_USERS ORDER BY USERNAME"

SCHEMA_TABLES_QUERY: Final[str] = (
    "SELECT OWNER AS SCHEMA_NAME, TABLE_NAME, TEMPORARY, PARTITIONED, NUM_ROWS, LAST_ANALYZED "
    "FROM ALL_TABLES WHERE OWNER = ? ORDER BY TABLE_NAME"
)

SCHEMA_COLUMNS_QUERY: Final[str] = (
    "SELECT C.COLUMN_NAME, C.DATA_TYPE, C.DATA_LENGTH, C.DATA_PRECISION, C.DATA_SCALE, "
    "C.NULLABLE, C.DATA_DEFAULT, C.COLUMN_ID, CC.COMMENTS AS \"COMMENT\" "
    "FROM ALL_TAB_COLUMNS C LEFT JOIN ALL_COL_COMMENTS CC "
    "ON CC.OWNER = C.OWNER AND CC.TABLE_NAME = C.TABLE_NAME AND CC.COLUMN_NAME = C.COLUMN_NAME "
    "WHERE C.OWNER = ? AND C.TABLE_NAME = ? ORDER BY C.COLUMN_ID"
)

SCHEMA_TABLE_COMMENT_QUERY: Final[str] = (
    "SELECT COMMENTS FROM ALL_TAB_COMMENTS WHERE OWNER = ? AND TABLE_NAME = ?"
)

SCHEMA_INDEXES_QUERY: Final[str] = (
    "SELECT I.INDEX_NAME, I.UNIQUENESS, I.INDEX_TYPE, C.COLUMN_NAME, "
    "C.COLUMN_POSITION, C.DESCEND, I.STATUS "
    "FROM ALL_INDEXES I JOIN ALL_IND_COLUMNS C "
    "ON C.INDEX_OWNER = I.OWNER AND C.INDEX_NAME = I.INDEX_NAME "
    "AND C.TABLE_OWNER = I.TABLE_OWNER AND C.TABLE_NAME = I.TABLE_NAME "
    "WHERE I.TABLE_OWNER = ? AND I.TABLE_NAME = ? "
    "ORDER BY I.INDEX_NAME, C.COLUMN_POSITION"
)

_SCHEMA_STATS_QUERY_TEMPLATE: Final[str] = (
    "SELECT TABLE_NAME, NUM_ROWS, BLOCKS, AVG_ROW_LEN, SAMPLE_SIZE, LAST_ANALYZED, STALE_STATS "
    "FROM ALL_TAB_STATISTICS WHERE TABLE_OWNER = ?{table_filter} ORDER BY TABLE_NAME"
)

_SCHEMA_STATS_TABLE_FILTER: Final[str] = " AND TABLE_NAME = ?"


def build_server_parameters_query(name_count: int) -> str:
    """Return the parameter query with one qmark placeholder per requested name."""

    if name_count < 1:
        raise ValueError("server parameter query requires at least one name")
    placeholders = ", ".join("?" for _ in range(name_count))
    return _SERVER_PARAMETERS_QUERY_TEMPLATE.format(placeholders=placeholders)


def build_schema_stats_query(*, table_filtered: bool) -> str:
    """Return the statistics query, optionally constrained to one table name."""

    table_filter = _SCHEMA_STATS_TABLE_FILTER if table_filtered else ""
    return _SCHEMA_STATS_QUERY_TEMPLATE.format(table_filter=table_filter)


__all__ = [
    "SCHEMA_COLUMNS_QUERY",
    "SCHEMA_DATABASES_QUERY",
    "SCHEMA_INDEXES_QUERY",
    "SCHEMA_TABLES_QUERY",
    "SCHEMA_TABLE_COMMENT_QUERY",
    "SERVER_ALL_PARAMETERS_QUERY",
    "SERVER_FILTERED_PARAMETERS_QUERY",
    "SERVER_INSTANCE_QUERY",
    "SERVER_VERSIONS_QUERY",
    "build_schema_stats_query",
    "build_server_parameters_query",
]
