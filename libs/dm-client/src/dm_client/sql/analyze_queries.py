"""SQL templates for ``DBMS_STATS`` table analysis.

The analysis statement and the statistics lookup use qmark bind parameters
only; no caller value is interpolated into SQL text.
"""

from __future__ import annotations

from typing import Final

TABLE_STATS_QUERY: Final[str] = (
    "SELECT NUM_ROWS, LAST_ANALYZED FROM ALL_TAB_STATISTICS "
    "WHERE TABLE_OWNER = ? AND TABLE_NAME = ? AND PARTITION_NAME IS NULL"
)

_PARTITION_STATS_QUERY: Final[str] = (
    "SELECT NUM_ROWS, LAST_ANALYZED FROM ALL_TAB_STATISTICS "
    "WHERE TABLE_OWNER = ? AND TABLE_NAME = ? AND PARTITION_NAME = ?"
)

GATHER_TABLE_STATS_CALL: Final[str] = (
    "CALL DBMS_STATS.GATHER_TABLE_STATS(?, ?, ?, ?, ?, ?, ?, ?, ?)"
)


def build_table_stats_query(*, partitioned: bool) -> str:
    """Return the table-level or partition-level statistics query."""

    return _PARTITION_STATS_QUERY if partitioned else TABLE_STATS_QUERY


def build_gather_table_stats_call() -> str:
    """Return the nine-argument ``DBMS_STATS`` analysis call."""

    return GATHER_TABLE_STATS_CALL


__all__ = [
    "GATHER_TABLE_STATS_CALL",
    "TABLE_STATS_QUERY",
    "build_gather_table_stats_call",
    "build_table_stats_query",
]
