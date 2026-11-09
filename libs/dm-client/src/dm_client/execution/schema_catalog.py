"""Read-only DM catalog execution for DDL, constraints and object listings."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Final

from dm_client.domain.enums import ConstraintType, InspectionKind, ObjectType, SqlStatementType
from dm_client.domain.errors import ObjectNotFoundError, QueryError, UnsupportedObjectError
from dm_client.domain.results import (
    ColumnDefinition,
    DatabaseRow,
    DdlResult,
    InspectionResult,
    QueryResult,
    TargetMetadata,
)
from dm_client.execution.inspection_support import (
    effective_schema,
    fetch_all,
    resolve_target,
    text_value,
)
from dm_client.execution.tabular import build_metadata
from dm_client.sql.catalog_queries import (
    DEFAULT_OBJECT_TYPES,
    OBJECT_EXISTS_QUERY,
    SCHEMA_DDL_QUERY,
    build_referenced_columns_query,
    build_schema_constraint_columns_query,
    build_schema_constraints_query,
    build_schema_objects_query,
)

if TYPE_CHECKING:
    from dm_client.domain.requests import SchemaConstraintsRequest, SchemaDdlRequest, SchemaObjectsRequest
    from dm_client.domain.values import DatabaseParameters, DatabaseValue
    from dm_client.ports.driver import DmConnection, DmCursor, DriverRow

_CONSTRAINT_TYPES: Final[dict[str, ConstraintType]] = {
    "P": ConstraintType.PRIMARY_KEY,
    "U": ConstraintType.UNIQUE,
    "R": ConstraintType.FOREIGN_KEY,
    "C": ConstraintType.CHECK,
}

_OBJECT_TYPE_VALUES: Final[dict[str, str]] = {kind.value.upper(): kind.value for kind in ObjectType}

_CONSTRAINT_COLUMNS: Final[tuple[ColumnDefinition, ...]] = (
    ColumnDefinition(name="CONSTRAINT_NAME", type_name="VARCHAR", nullable=False, ordinal=0),
    ColumnDefinition(name="CONSTRAINT_TYPE", type_name="VARCHAR", nullable=False, ordinal=1),
    ColumnDefinition(name="TABLE_NAME", type_name="VARCHAR", nullable=False, ordinal=2),
    ColumnDefinition(name="COLUMNS", type_name="JSON", nullable=False, ordinal=3),
    ColumnDefinition(name="SEARCH_CONDITION", type_name="VARCHAR", ordinal=4),
    ColumnDefinition(name="REFERENCED_OWNER", type_name="VARCHAR", ordinal=5),
    ColumnDefinition(name="REFERENCED_TABLE", type_name="VARCHAR", ordinal=6),
    ColumnDefinition(name="REFERENCED_COLUMNS", type_name="JSON", nullable=False, ordinal=7),
    ColumnDefinition(name="DELETE_RULE", type_name="VARCHAR", ordinal=8),
    ColumnDefinition(name="STATUS", type_name="VARCHAR", ordinal=9),
    ColumnDefinition(name="VALIDATED", type_name="VARCHAR", ordinal=10),
)

_OBJECT_COLUMNS: Final[tuple[ColumnDefinition, ...]] = (
    ColumnDefinition(name="OBJECT_TYPE", type_name="VARCHAR", nullable=False, ordinal=0),
    ColumnDefinition(name="OBJECT_NAME", type_name="VARCHAR", nullable=False, ordinal=1),
    ColumnDefinition(name="STATUS", type_name="VARCHAR", ordinal=2),
    ColumnDefinition(name="CREATED", type_name="TIMESTAMP", ordinal=3),
    ColumnDefinition(name="LAST_DDL_TIME", type_name="TIMESTAMP", ordinal=4),
)

_CONSTRAINT_ROW_WIDTH: Final[int] = 9
_CONS_COLUMN_ROW_WIDTH: Final[int] = 5
_REFERENCED_ROW_WIDTH: Final[int] = 5
_OBJECT_ROW_WIDTH: Final[int] = 5


@dataclass(frozen=True, slots=True, kw_only=True)
class _ConstraintKey:
    """Owner-qualified identity of a referenced constraint."""

    owner: str
    name: str


@dataclass(frozen=True, slots=True, kw_only=True)
class _ReferencedConstraint:
    """Referenced table and ordered columns of one foreign key constraint."""

    table: str
    columns: tuple[str, ...]


def run_schema_ddl(
    connection: DmConnection,
    request: SchemaDdlRequest,
    target_label: str,
    *,
    target: TargetMetadata | None = None,
) -> DdlResult:
    """Return the DM-generated DDL text for one catalog object."""

    started_at = datetime.now(timezone.utc)
    resolved_target = resolve_target(connection, target_label, target)
    schema = effective_schema(connection, request.schema)
    object_type = request.object_type.value.upper()
    cursor = connection.cursor()
    try:
        cursor.execute(SCHEMA_DDL_QUERY, (object_type, request.name.value, schema))
        rows = fetch_all(cursor)
        ddl = _first_text(rows)
        if not ddl:
            _raise_missing_ddl(cursor, request, schema, object_type)
    finally:
        cursor.close()
    metadata = build_metadata(SqlStatementType.SELECT, started_at, resolved_target, row_count=1)
    return DdlResult(
        object_type=request.object_type,
        schema=schema,
        name=request.name.value,
        ddl=ddl,
        metadata=metadata,
    )


def run_schema_constraints(
    connection: DmConnection,
    request: SchemaConstraintsRequest,
    target_label: str,
    target: TargetMetadata | None,
) -> InspectionResult:
    """Return constraints of the schema or one table, resolving foreign key targets."""

    started_at = datetime.now(timezone.utc)
    resolved_target = resolve_target(connection, target_label, target)
    schema = effective_schema(connection, request.schema)
    table = request.table.value if request.table is not None else None
    filtered = table is not None
    parameters: DatabaseParameters = (schema,) if table is None else (schema, table)
    cursor = connection.cursor()
    try:
        cursor.execute(build_schema_constraints_query(table_filtered=filtered), parameters)
        constraint_rows = fetch_all(cursor)
        cursor.execute(build_schema_constraint_columns_query(table_filtered=filtered), parameters)
        column_rows = fetch_all(cursor)
        references = _foreign_key_references(constraint_rows)
        referenced = _load_referenced_columns(cursor, references) if references else {}
    finally:
        cursor.close()

    columns_by_constraint = _columns_by_constraint(column_rows)
    rows = tuple(
        _constraint_row(row, columns_by_constraint, referenced) for row in constraint_rows
    )
    metadata = build_metadata(SqlStatementType.SELECT, started_at, resolved_target, row_count=len(rows))
    query = QueryResult(columns=_CONSTRAINT_COLUMNS, rows=rows, metadata=metadata)
    return InspectionResult(kind=InspectionKind.SCHEMA_CONSTRAINTS, query=query)


def run_schema_objects(
    connection: DmConnection,
    request: SchemaObjectsRequest,
    target_label: str,
    target: TargetMetadata | None,
) -> InspectionResult:
    """List catalog objects of the schema, optionally restricted to one type."""

    started_at = datetime.now(timezone.utc)
    resolved_target = resolve_target(connection, target_label, target)
    schema = effective_schema(connection, request.schema)
    if request.object_type is None:
        object_types = tuple(object_type.value.upper() for object_type in DEFAULT_OBJECT_TYPES)
    else:
        object_types = (request.object_type.value.upper(),)
    cursor = connection.cursor()
    try:
        cursor.execute(build_schema_objects_query(len(object_types)), (schema, *object_types))
        raw_rows = fetch_all(cursor)
    finally:
        cursor.close()

    rows = tuple(_object_row(row) for row in raw_rows)
    metadata = build_metadata(SqlStatementType.SELECT, started_at, resolved_target, row_count=len(rows))
    query = QueryResult(columns=_OBJECT_COLUMNS, rows=rows, metadata=metadata)
    return InspectionResult(kind=InspectionKind.SCHEMA_OBJECTS, query=query)


def _first_text(rows: tuple[DriverRow, ...]) -> str:
    if not rows or len(rows[0]) < 1 or rows[0][0] is None:
        return ""
    return text_value(rows[0][0]).strip()


def _raise_missing_ddl(
    cursor: DmCursor,
    request: SchemaDdlRequest,
    schema: str,
    object_type: str,
) -> None:
    cursor.execute(OBJECT_EXISTS_QUERY, (schema, request.name.value, object_type))
    rows = fetch_all(cursor)
    count = rows[0][0] if rows and len(rows[0]) >= 1 else None
    qualified = f"{request.object_type.value} {schema}.{request.name.value}"
    if text_value(count) not in {"", "0"}:
        raise UnsupportedObjectError(
            f"DBMS_METADATA.GET_DDL returned no DDL for {qualified}",
            hint="DM may not generate DDL for this object type",
        )
    raise ObjectNotFoundError(
        f"{qualified} was not found",
        hint="verify the schema, object name and object type",
    )


def _foreign_key_references(rows: tuple[DriverRow, ...]) -> tuple[_ConstraintKey, ...]:
    references: list[_ConstraintKey] = []
    seen: set[_ConstraintKey] = set()
    for row in rows:
        if len(row) < 6:
            continue
        key = _reference_key(row[4], row[5])
        if key is not None and key not in seen:
            seen.add(key)
            references.append(key)
    return tuple(references)


def _reference_key(owner: DatabaseValue, name: DatabaseValue) -> _ConstraintKey | None:
    if owner is None or name is None:
        return None
    return _ConstraintKey(owner=text_value(owner), name=text_value(name))


def _load_referenced_columns(
    cursor: DmCursor,
    references: tuple[_ConstraintKey, ...],
) -> dict[_ConstraintKey, _ReferencedConstraint]:
    parameters: tuple[DatabaseValue, ...] = tuple(
        value for reference in references for value in (reference.owner, reference.name)
    )
    cursor.execute(build_referenced_columns_query(len(references)), parameters)
    raw_rows = fetch_all(cursor)
    tables: dict[_ConstraintKey, str] = {}
    columns: dict[_ConstraintKey, list[tuple[int | None, str]]] = {}
    for row in raw_rows:
        if len(row) < _REFERENCED_ROW_WIDTH:
            raise QueryError("ALL_CONS_COLUMNS returned an unexpected row shape")
        key = _ConstraintKey(owner=text_value(row[0]), name=text_value(row[1]))
        tables.setdefault(key, text_value(row[2]))
        columns.setdefault(key, []).append((_position_value(row[4]), text_value(row[3])))
    return {
        key: _ReferencedConstraint(table=tables[key], columns=_ordered_columns(values))
        for key, values in columns.items()
    }


def _columns_by_constraint(rows: tuple[DriverRow, ...]) -> dict[str, tuple[str, ...]]:
    collected: dict[str, list[tuple[int | None, str]]] = {}
    for row in rows:
        if len(row) < _CONS_COLUMN_ROW_WIDTH:
            raise QueryError("ALL_CONS_COLUMNS returned an unexpected row shape")
        collected.setdefault(text_value(row[1]), []).append((_position_value(row[4]), text_value(row[3])))
    return {name: _ordered_columns(entries) for name, entries in collected.items()}


def _ordered_columns(entries: list[tuple[int | None, str]]) -> tuple[str, ...]:
    return tuple(column for _, column in sorted(entries, key=_column_order))


def _column_order(entry: tuple[int | None, str]) -> tuple[int, int, str]:
    position, column = entry
    return (0, position, column) if position is not None else (1, 0, column)


def _position_value(value: DatabaseValue) -> int | None:
    if value is None:
        return None
    try:
        return int(text_value(value))
    except ValueError:
        return None


def _constraint_row(
    row: DriverRow,
    columns_by_constraint: dict[str, tuple[str, ...]],
    referenced: dict[_ConstraintKey, _ReferencedConstraint],
) -> DatabaseRow:
    if len(row) < _CONSTRAINT_ROW_WIDTH:
        raise QueryError("ALL_CONSTRAINTS returned an unexpected row shape")
    name = text_value(row[0])
    reference = _reference_key(row[4], row[5])
    referenced_owner: str | None = None
    referenced_table: str | None = None
    referenced_columns: tuple[str, ...] = ()
    if reference is not None:
        referenced_owner = reference.owner
        resolved = referenced.get(reference)
        if resolved is not None:
            referenced_table = resolved.table
            referenced_columns = resolved.columns
    return DatabaseRow.from_values(
        (
            name,
            _constraint_type(row[1]),
            text_value(row[2]),
            list(columns_by_constraint.get(name, ())),
            _optional_text(row[3]),
            referenced_owner,
            referenced_table,
            list(referenced_columns),
            _optional_text(row[6]),
            _optional_text(row[7]),
            _optional_text(row[8]),
        )
    )


def _constraint_type(value: DatabaseValue) -> ConstraintType:
    if value is None:
        return ConstraintType.UNKNOWN
    return _CONSTRAINT_TYPES.get(text_value(value).strip().upper(), ConstraintType.UNKNOWN)


def _optional_text(value: DatabaseValue) -> str | None:
    return None if value is None else text_value(value)


def _object_row(row: DriverRow) -> DatabaseRow:
    if len(row) < _OBJECT_ROW_WIDTH:
        raise QueryError("ALL_OBJECTS returned an unexpected row shape")
    values = list(row[: _OBJECT_ROW_WIDTH])
    values[0] = _object_type_value(values[0])
    return DatabaseRow.from_values(values)


def _object_type_value(value: DatabaseValue) -> DatabaseValue:
    if value is None:
        return None
    text = text_value(value)
    return _OBJECT_TYPE_VALUES.get(text.strip().upper(), text)


__all__ = [
    "run_schema_constraints",
    "run_schema_ddl",
    "run_schema_objects",
]
