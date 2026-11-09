"""Unit tests for DM catalog DDL, constraint and object inspection."""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

import pytest

from dm_client.domain.configuration import DmConnectionConfig, SecretValue
from dm_client.domain.enums import ConstraintType, InspectionKind, ObjectType
from dm_client.domain.errors import ObjectNotFoundError, UnsupportedObjectError
from dm_client.domain.requests import (
    SchemaConstraintsRequest,
    SchemaDdlRequest,
    SchemaObjectsRequest,
)
from dm_client.domain.results import DdlResult, InspectionResult
from dm_client.domain.values import ObjectName, SchemaName, TableName
from dm_client.execution.inspection import run_inspection
from dm_client.execution.schema_catalog import run_schema_ddl
from dm_client.execution.session import DmSession
from dm_client.ports.driver import DriverColumn
from dm_client.sql.catalog_queries import DEFAULT_OBJECT_TYPES

if TYPE_CHECKING:
    from collections.abc import Sequence

    from dm_client.domain.values import DatabaseValue

CONSTRAINT_COLUMNS = (
    "CONSTRAINT_NAME",
    "CONSTRAINT_TYPE",
    "TABLE_NAME",
    "COLUMNS",
    "SEARCH_CONDITION",
    "REFERENCED_OWNER",
    "REFERENCED_TABLE",
    "REFERENCED_COLUMNS",
    "DELETE_RULE",
    "STATUS",
    "VALIDATED",
)
OBJECT_COLUMNS = (
    "OBJECT_TYPE",
    "OBJECT_NAME",
    "STATUS",
    "CREATED",
    "LAST_DDL_TIME",
)
CONSTRAINTS_QUERY_MARKER = "FROM ALL_CONSTRAINTS"
CONS_COLUMNS_QUERY_MARKER = "FROM ALL_CONS_COLUMNS WHERE OWNER = ?"
REFERENCED_COLUMNS_QUERY_MARKER = "FROM ALL_CONS_COLUMNS WHERE (OWNER = ? AND CONSTRAINT_NAME = ?)"


@dataclass(frozen=True)
class QueryFixture:
    """Rows and normalized columns returned for one scripted query."""

    columns: tuple[DriverColumn, ...]
    rows: tuple[tuple[DatabaseValue, ...], ...]


def columns(*names: str) -> tuple[DriverColumn, ...]:
    return tuple(DriverColumn(name=name, type_name="VARCHAR") for name in names)


class FakeCursor:
    def __init__(
        self,
        fixtures: dict[str, QueryFixture],
        executed: list[tuple[str, tuple[object, ...]]],
        threads: list[int],
    ) -> None:
        self._fixtures = fixtures
        self._executed = executed
        self._threads = threads
        self._description: Sequence[DriverColumn] | None = None
        self._rows: list[tuple[DatabaseValue, ...]] = []
        self.closed = False

    @property
    def description(self) -> Sequence[DriverColumn] | None:
        return self._description

    @property
    def rowcount(self) -> int:
        return len(self._rows)

    def execute(self, sql: str, parameters: tuple[object, ...] = ()) -> None:
        self._threads.append(threading.get_ident())
        self._executed.append((sql, tuple(parameters)))
        fixture = _fixture_for(sql, self._fixtures)
        self._description = fixture.columns
        self._rows = list(fixture.rows)

    def fetchmany(self, size: int) -> Sequence[Sequence[object]]:
        batch = self._rows[:size]
        self._rows = self._rows[size:]
        return batch

    def close(self) -> None:
        self.closed = True


class FakeConnection:
    user = "APP"
    server_version = "8.1.4.80"
    current_schema = "APP"
    str_case_sensitive = False
    max_identifier_length = 128

    def __init__(
        self,
        fixtures: dict[str, QueryFixture],
        executed: list[tuple[str, tuple[object, ...]]],
        threads: list[int],
    ) -> None:
        self._fixtures = fixtures
        self._executed = executed
        self._threads = threads
        self.closed = False
        self.rollbacks = 0

    def cursor(self) -> FakeCursor:
        return FakeCursor(self._fixtures, self._executed, self._threads)

    def explain(self, sql: str) -> str:
        return f"plan for {sql}"

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closed = True


class FakeFactory:
    def __init__(self, connection: FakeConnection) -> None:
        self._connection = connection
        self.configs: list[DmConnectionConfig] = []

    def connect(self, config: DmConnectionConfig) -> FakeConnection:
        self.configs.append(config)
        return self._connection


def connection_parts(
    fixtures: dict[str, QueryFixture],
) -> tuple[FakeConnection, list[tuple[str, tuple[object, ...]]], list[int]]:
    executed: list[tuple[str, tuple[object, ...]]] = []
    threads: list[int] = []
    return FakeConnection(fixtures, executed, threads), executed, threads


def _fixture_for(sql: str, fixtures: dict[str, QueryFixture]) -> QueryFixture:
    for marker, fixture in fixtures.items():
        if marker in sql:
            return fixture
    raise AssertionError(f"unexpected query: {sql}")


def ddl_fixture(sql_text: str) -> dict[str, QueryFixture]:
    return {
        "DBMS_METADATA.GET_DDL": QueryFixture(
            columns=columns("DDL"),
            rows=((sql_text,),),
        )
    }


@pytest.mark.parametrize(
    ("object_type", "sql_text"),
    (
        (ObjectType.TABLE, "CREATE TABLE APP.T (ID INT)"),
        (ObjectType.VIEW, "CREATE VIEW APP.V AS SELECT 1"),
        (ObjectType.INDEX, "CREATE INDEX APP.I ON APP.T (ID)"),
        (ObjectType.SEQUENCE, "CREATE SEQUENCE APP.S START WITH 1"),
    ),
)
def test_schema_ddl_returns_ddl_and_binds_type_name_and_effective_schema(
    object_type: ObjectType,
    sql_text: str,
) -> None:
    connection, executed, _ = connection_parts(ddl_fixture(sql_text))

    result = run_schema_ddl(
        connection,
        SchemaDdlRequest(object_type=object_type, name=ObjectName(value="T")),
        "dev",
    )

    assert result.object_type is object_type
    assert result.schema == "APP"
    assert result.name == "T"
    assert result.ddl == sql_text
    assert result.metadata.row_count == 1
    sql, parameters = executed[0]
    assert sql == "SELECT DBMS_METADATA.GET_DDL(?, ?, ?) FROM DUAL"
    assert parameters == (object_type.value.upper(), "T", "APP")


def test_schema_ddl_uses_an_explicit_schema() -> None:
    connection, executed, _ = connection_parts(ddl_fixture("CREATE TABLE OTHER.T (ID INT)"))

    result = run_schema_ddl(
        connection,
        SchemaDdlRequest(
            object_type=ObjectType.TABLE,
            name=ObjectName(value="T"),
            schema=SchemaName(value="OTHER"),
        ),
        "dev",
    )

    assert result.schema == "OTHER"
    assert executed[0][1] == ("TABLE", "T", "OTHER")


def test_schema_ddl_of_a_missing_object_raises_object_not_found() -> None:
    fixtures = {
        "DBMS_METADATA.GET_DDL": QueryFixture(columns=columns("DDL"), rows=((None,),)),
        "ALL_OBJECTS": QueryFixture(columns=columns("COUNT"), rows=((0,),)),
    }
    connection, executed, _ = connection_parts(fixtures)

    with pytest.raises(ObjectNotFoundError, match=r"table APP\.MISSING"):
        run_schema_ddl(
            connection,
            SchemaDdlRequest(object_type=ObjectType.TABLE, name=ObjectName(value="MISSING")),
            "dev",
        )

    assert [sql for sql, _ in executed][1].startswith("SELECT COUNT(*) FROM ALL_OBJECTS")
    assert executed[1][1] == ("APP", "MISSING", "TABLE")


def test_schema_ddl_without_generated_text_for_an_existing_object_is_unsupported() -> None:
    fixtures = {
        "DBMS_METADATA.GET_DDL": QueryFixture(columns=columns("DDL"), rows=((None,),)),
        "ALL_OBJECTS": QueryFixture(columns=columns("COUNT"), rows=((1,),)),
    }
    connection, _, _ = connection_parts(fixtures)

    with pytest.raises(UnsupportedObjectError, match=r"synonym APP\.S"):
        run_schema_ddl(
            connection,
            SchemaDdlRequest(object_type=ObjectType.SYNONYM, name=ObjectName(value="S")),
            "dev",
        )


def test_schema_constraints_maps_types_columns_and_referenced_targets() -> None:
    fixtures = {
        CONSTRAINTS_QUERY_MARKER: QueryFixture(
            columns=columns(
                "CONSTRAINT_NAME",
                "CONSTRAINT_TYPE",
                "TABLE_NAME",
                "SEARCH_CONDITION",
                "R_OWNER",
                "R_CONSTRAINT_NAME",
                "DELETE_RULE",
                "STATUS",
                "VALIDATED",
            ),
            rows=(
                ("CK_T_ID", "C", "T", '"ID" > 0', None, None, None, "ENABLED", "VALIDATED"),
                ("PK_T", "P", "T", None, None, None, None, "ENABLED", "VALIDATED"),
                ("FK_T_PARENT", "R", "T", None, "APP", "PK_PARENT", "NO ACTION", "ENABLED", "NOT VALIDATED"),
            ),
        ),
        CONS_COLUMNS_QUERY_MARKER: QueryFixture(
            columns=columns("OWNER", "CONSTRAINT_NAME", "TABLE_NAME", "COLUMN_NAME", "POSITION"),
            rows=(
                ("APP", "CK_T_ID", "T", "ID", None),
                ("APP", "PK_T", "T", "CODE", 2),
                ("APP", "PK_T", "T", "ID", 1),
                ("APP", "FK_T_PARENT", "T", "PARENT_ID", 1),
            ),
        ),
        REFERENCED_COLUMNS_QUERY_MARKER: QueryFixture(
            columns=columns("OWNER", "CONSTRAINT_NAME", "TABLE_NAME", "COLUMN_NAME", "POSITION"),
            rows=(("APP", "PK_PARENT", "PARENT", "ID", 1),),
        ),
    }
    connection, executed, _ = connection_parts(fixtures)

    result = run_inspection(connection, SchemaConstraintsRequest(), "dev")

    assert isinstance(result, InspectionResult)
    assert result.kind is InspectionKind.SCHEMA_CONSTRAINTS
    assert [column.name for column in result.query.columns] == list(CONSTRAINT_COLUMNS)
    assert result.query.metadata.row_count == 3
    rows = {str(row.values[0]): row.values for row in result.query.rows}

    check = rows["CK_T_ID"]
    assert check[1] is ConstraintType.CHECK
    assert check[3] == ["ID"]
    assert check[4] == '"ID" > 0'
    assert check[7] == []

    primary = rows["PK_T"]
    assert primary[1] is ConstraintType.PRIMARY_KEY
    assert primary[3] == ["ID", "CODE"]

    foreign = rows["FK_T_PARENT"]
    assert foreign[1] is ConstraintType.FOREIGN_KEY
    assert foreign[3] == ["PARENT_ID"]
    assert foreign[5] == "APP"
    assert foreign[6] == "PARENT"
    assert foreign[7] == ["ID"]
    assert foreign[8] == "NO ACTION"

    assert executed[0][1] == ("APP",)
    assert executed[1][1] == ("APP",)
    assert executed[2][1] == ("APP", "PK_PARENT")


def test_schema_constraints_filters_one_table_and_keeps_missing_references_empty() -> None:
    fixtures = {
        CONSTRAINTS_QUERY_MARKER: QueryFixture(
            columns=columns(
                "CONSTRAINT_NAME",
                "CONSTRAINT_TYPE",
                "TABLE_NAME",
                "SEARCH_CONDITION",
                "R_OWNER",
                "R_CONSTRAINT_NAME",
                "DELETE_RULE",
                "STATUS",
                "VALIDATED",
            ),
            rows=(("FK_ORPHAN", "R", "T", None, "OTHER", "PK_ABSENT", "CASCADE", "ENABLED", "VALIDATED"),),
        ),
        CONS_COLUMNS_QUERY_MARKER: QueryFixture(
            columns=columns("OWNER", "CONSTRAINT_NAME", "TABLE_NAME", "COLUMN_NAME", "POSITION"),
            rows=(("APP", "FK_ORPHAN", "T", "PARENT_ID", 1),),
        ),
        REFERENCED_COLUMNS_QUERY_MARKER: QueryFixture(
            columns=columns("OWNER", "CONSTRAINT_NAME", "TABLE_NAME", "COLUMN_NAME", "POSITION"),
            rows=(),
        ),
    }
    connection, executed, _ = connection_parts(fixtures)

    result = run_inspection(
        connection,
        SchemaConstraintsRequest(table=TableName(value="T")),
        "dev",
    )

    assert isinstance(result, InspectionResult)
    assert executed[0][1] == ("APP", "T")
    assert "AND TABLE_NAME = ?" in executed[0][0]
    assert "AND TABLE_NAME = ?" in executed[1][0]
    values = result.query.rows[0].values
    assert values[5] == "OTHER"
    assert values[6] is None
    assert values[7] == []


def test_schema_objects_defaults_to_common_types_and_excludes_indexes() -> None:
    fixtures = {
        "ALL_OBJECTS": QueryFixture(
            columns=columns("OBJECT_TYPE", "OBJECT_NAME", "STATUS", "CREATED", "LAST_DDL_TIME"),
            rows=(
                ("TABLE", "A_TABLE", "VALID", datetime(2026, 1, 1), datetime(2026, 1, 2)),
                ("VIEW", "A_VIEW", "VALID", datetime(2026, 1, 3), datetime(2026, 1, 4)),
            ),
        )
    }
    connection, executed, _ = connection_parts(fixtures)

    result = run_inspection(connection, SchemaObjectsRequest(), "dev")

    assert isinstance(result, InspectionResult)
    assert result.kind is InspectionKind.SCHEMA_OBJECTS
    assert [column.name for column in result.query.columns] == list(OBJECT_COLUMNS)
    assert [row.values for row in result.query.rows] == [
        ("table", "A_TABLE", "VALID", datetime(2026, 1, 1), datetime(2026, 1, 2)),
        ("view", "A_VIEW", "VALID", datetime(2026, 1, 3), datetime(2026, 1, 4)),
    ]
    sql, parameters = executed[0]
    assert "OBJECT_TYPE IN (?, ?, ?, ?, ?, ?, ?, ?)" in sql
    assert "OBJECT_TYPE <> 'PACKAGE BODY'" in sql
    assert "ORDER BY OBJECT_TYPE, OBJECT_NAME" in sql
    bound_types = parameters[1:]
    assert "INDEX" not in bound_types
    assert bound_types == tuple(object_type.value.upper() for object_type in DEFAULT_OBJECT_TYPES)


def test_schema_objects_explicit_type_selects_only_indexes() -> None:
    fixtures = {
        "ALL_OBJECTS": QueryFixture(
            columns=columns("OBJECT_TYPE", "OBJECT_NAME", "STATUS", "CREATED", "LAST_DDL_TIME"),
            rows=(("INDEX", "IDX_A", "VALID", None, None),),
        )
    }
    connection, executed, _ = connection_parts(fixtures)

    result = run_inspection(connection, SchemaObjectsRequest(object_type=ObjectType.INDEX), "dev")

    assert isinstance(result, InspectionResult)
    assert [row.values for row in result.query.rows] == [("index", "IDX_A", "VALID", None, None)]
    assert executed[0][1] == ("APP", "INDEX")
    assert "OBJECT_TYPE IN (?)" in executed[0][0]


def test_session_execute_catalog_uses_the_worker_thread() -> None:
    connection, _, threads = connection_parts(ddl_fixture("CREATE TABLE APP.T (ID INT)"))
    factory = FakeFactory(connection)
    config = DmConnectionConfig(
        host="127.0.0.1",
        port=15237,
        user="APP",
        password=SecretValue(_value="secret"),
        schema=SchemaName(value="APP"),
    )

    async def catalog() -> DdlResult:
        async with DmSession(config, factory, "dev") as session:
            return await session.execute_catalog(
                SchemaDdlRequest(object_type=ObjectType.TABLE, name=ObjectName(value="T"))
            )

    result = asyncio.run(catalog())

    assert result.ddl == "CREATE TABLE APP.T (ID INT)"
    assert threads
    assert threads[0] != threading.get_ident()
    assert connection.closed is True
