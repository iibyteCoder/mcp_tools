from __future__ import annotations

import pytest

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
from mysql_client.domain.values import DatabaseName, TableName
from mysql_client.sql.inspection import build_inspection_query


def test_identifier_models_reject_unsafe_empty_values() -> None:
    with pytest.raises(ValueError):
        DatabaseName(value=" ")
    with pytest.raises(ValueError):
        TableName(value="orders\x00archive")


@pytest.mark.parametrize(
    ("inspection_request", "command", "expected_parameters"),
    [
        (ServerInspectRequest(), InspectionCommand.SERVER_INSPECT, ()),
        (ServerCapabilitiesRequest(), InspectionCommand.SERVER_CAPABILITIES, ()),
        (SchemaDatabasesRequest(), InspectionCommand.SCHEMA_DATABASES, ()),
        (
            SchemaTablesRequest(database=DatabaseName(value="billing")),
            InspectionCommand.SCHEMA_TABLES,
            ("billing",),
        ),
        (
            SchemaDescribeRequest(database=DatabaseName(value="billing"), table=TableName(value="invoices")),
            InspectionCommand.SCHEMA_DESCRIBE,
            ("billing", "invoices"),
        ),
        (
            SchemaIndexesRequest(database=DatabaseName(value="billing"), table=TableName(value="invoices")),
            InspectionCommand.SCHEMA_INDEXES,
            ("billing", "invoices"),
        ),
        (
            SchemaStatsRequest(database=DatabaseName(value="billing"), table=TableName(value="invoices")),
            InspectionCommand.SCHEMA_STATS,
            ("billing", "invoices", "invoices"),
        ),
    ],
)
def test_inspection_queries_are_read_only_and_bind_targets(
    inspection_request: InspectionRequest,
    command: InspectionCommand,
    expected_parameters: tuple[object, ...],
) -> None:
    definition = build_inspection_query(inspection_request)

    assert definition.command is command
    assert definition.statement_type is SqlStatementType.SELECT
    assert definition.parameters == expected_parameters
    assert "USE " not in definition.sql
    assert "%s" in definition.sql if expected_parameters else "%s" not in definition.sql
    assert "invoices" not in definition.sql


def test_stats_without_table_binds_null_filter() -> None:
    definition = build_inspection_query(SchemaStatsRequest())

    assert definition.parameters == (None, None, None)
    assert definition.sql.count("%s") == len(definition.parameters)
