"""SQL templates for DM catalog DDL, constraints and object listing.

Caller input reaches the database only through qmark bind parameters. The only
dynamic fragments are placeholder lists and optional clauses; no caller value is
interpolated into SQL text.
"""

from __future__ import annotations

from typing import Final

from dm_client.domain.enums import ObjectType

SCHEMA_DDL_QUERY: Final[str] = "SELECT DBMS_METADATA.GET_DDL(?, ?, ?) FROM DUAL"

OBJECT_EXISTS_QUERY: Final[str] = (
    "SELECT COUNT(*) FROM ALL_OBJECTS WHERE OWNER = ? AND OBJECT_NAME = ? AND OBJECT_TYPE = ?"
)

DEFAULT_OBJECT_TYPES: Final[tuple[ObjectType, ...]] = (
    ObjectType.TABLE,
    ObjectType.VIEW,
    ObjectType.SEQUENCE,
    ObjectType.SYNONYM,
    ObjectType.PROCEDURE,
    ObjectType.FUNCTION,
    ObjectType.PACKAGE,
    ObjectType.TRIGGER,
)

_CONSTRAINTS_QUERY_TEMPLATE: Final[str] = (
    "SELECT CONSTRAINT_NAME, CONSTRAINT_TYPE, TABLE_NAME, SEARCH_CONDITION, R_OWNER, "
    "R_CONSTRAINT_NAME, DELETE_RULE, STATUS, VALIDATED "
    "FROM ALL_CONSTRAINTS WHERE OWNER = ?{table_filter} "
    "ORDER BY TABLE_NAME, CONSTRAINT_NAME"
)

_CONS_COLUMNS_QUERY_TEMPLATE: Final[str] = (
    "SELECT OWNER, CONSTRAINT_NAME, TABLE_NAME, COLUMN_NAME, POSITION "
    "FROM ALL_CONS_COLUMNS WHERE OWNER = ?{table_filter} "
    "ORDER BY TABLE_NAME, CONSTRAINT_NAME, "
    "CASE WHEN POSITION IS NULL THEN 1 ELSE 0 END, POSITION, COLUMN_NAME"
)

_REFERENCED_CONS_COLUMNS_QUERY_TEMPLATE: Final[str] = (
    "SELECT OWNER, CONSTRAINT_NAME, TABLE_NAME, COLUMN_NAME, POSITION "
    "FROM ALL_CONS_COLUMNS WHERE {pairs} "
    "ORDER BY OWNER, CONSTRAINT_NAME, "
    "CASE WHEN POSITION IS NULL THEN 1 ELSE 0 END, POSITION, COLUMN_NAME"
)

_SCHEMA_OBJECTS_QUERY_TEMPLATE: Final[str] = (
    "SELECT OBJECT_TYPE, OBJECT_NAME, STATUS, CREATED, LAST_DDL_TIME FROM ALL_OBJECTS "
    "WHERE OWNER = ? AND OBJECT_TYPE IN ({placeholders}) AND OBJECT_TYPE <> 'PACKAGE BODY' "
    "ORDER BY OBJECT_TYPE, OBJECT_NAME"
)

_TABLE_FILTER: Final[str] = " AND TABLE_NAME = ?"
_REFERENCE_PAIR: Final[str] = "(OWNER = ? AND CONSTRAINT_NAME = ?)"


def build_schema_constraints_query(*, table_filtered: bool) -> str:
    """Return the constraint query, optionally constrained to one table name."""

    return _CONSTRAINTS_QUERY_TEMPLATE.format(table_filter=_TABLE_FILTER if table_filtered else "")


def build_schema_constraint_columns_query(*, table_filtered: bool) -> str:
    """Return the constraint-column query, optionally constrained to one table."""

    return _CONS_COLUMNS_QUERY_TEMPLATE.format(table_filter=_TABLE_FILTER if table_filtered else "")


def build_referenced_columns_query(reference_count: int) -> str:
    """Return one lookup for the referenced columns of ``reference_count`` constraints."""

    if reference_count < 1:
        raise ValueError("referenced column lookup requires at least one constraint")
    pairs = " OR ".join(_REFERENCE_PAIR for _ in range(reference_count))
    return _REFERENCED_CONS_COLUMNS_QUERY_TEMPLATE.format(pairs=pairs)


def build_schema_objects_query(object_type_count: int) -> str:
    """Return the object query with one qmark placeholder per requested type."""

    if object_type_count < 1:
        raise ValueError("schema object query requires at least one object type")
    placeholders = ", ".join("?" for _ in range(object_type_count))
    return _SCHEMA_OBJECTS_QUERY_TEMPLATE.format(placeholders=placeholders)


__all__ = [
    "DEFAULT_OBJECT_TYPES",
    "OBJECT_EXISTS_QUERY",
    "SCHEMA_DDL_QUERY",
    "build_referenced_columns_query",
    "build_schema_constraint_columns_query",
    "build_schema_constraints_query",
    "build_schema_objects_query",
]
