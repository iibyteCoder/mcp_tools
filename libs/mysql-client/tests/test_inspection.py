from __future__ import annotations

import pytest

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
from mysql_client.domain.values import DatabaseName, TableName
from mysql_client.sql.inspection import (
    CURATED_SERVER_STATUS_NAMES,
    CURATED_SERVER_VARIABLE_NAMES,
    SENSITIVE_VARIABLE_MARKERS,
    SENSITIVE_VARIABLE_PATTERN,
    build_inspection_query,
)


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


def test_server_inspect_quotes_reserved_current_user_alias() -> None:
    definition = build_inspection_query(ServerInspectRequest())

    assert "CURRENT_USER() AS `current_user`" in definition.sql


def test_server_variables_default_binds_curated_names_and_redaction_pattern() -> None:
    definition = build_inspection_query(ServerMetricsRequest(kind=ServerMetricKind.VARIABLES))

    assert definition.command is InspectionCommand.SERVER_VARIABLES
    assert definition.statement_type is SqlStatementType.SELECT
    assert "performance_schema.global_variables" in definition.sql
    assert "information_schema.GLOBAL_VARIABLES" not in definition.sql
    assert "AS name" in definition.sql
    assert "AS value" in definition.sql
    assert "AS redacted" in definition.sql
    assert "VARIABLE_NAME IN" in definition.sql
    assert definition.parameters[:2] == (SENSITIVE_VARIABLE_PATTERN, SENSITIVE_VARIABLE_PATTERN)
    assert definition.parameters[2:] == CURATED_SERVER_VARIABLE_NAMES
    assert len(CURATED_SERVER_VARIABLE_NAMES) > 0
    assert definition.sql.count("%s") == len(definition.parameters)
    predicate = definition.sql.split("WHERE", 1)[1]
    for name in CURATED_SERVER_VARIABLE_NAMES:
        assert name not in predicate


def test_server_variables_filter_binds_a_like_pattern_without_interpolation() -> None:
    definition = build_inspection_query(
        ServerMetricsRequest(kind=ServerMetricKind.VARIABLES, filter_text="Buffer_Pool")
    )

    assert "VARIABLE_NAME LIKE %s" in definition.sql
    assert "VARIABLE_NAME IN" not in definition.sql
    assert "Buffer_Pool" not in definition.sql
    assert definition.parameters[-1] == "%Buffer_Pool%"
    assert definition.parameters[2:-1] == ()


@pytest.mark.parametrize("kind", [ServerMetricKind.VARIABLES, ServerMetricKind.STATUS])
def test_server_metrics_all_omits_the_name_predicate(kind: ServerMetricKind) -> None:
    definition = build_inspection_query(ServerMetricsRequest(kind=kind, all=True))

    assert "VARIABLE_NAME IN" not in definition.sql
    assert "VARIABLE_NAME LIKE" not in definition.sql
    if kind is ServerMetricKind.VARIABLES:
        assert definition.parameters == (SENSITIVE_VARIABLE_PATTERN, SENSITIVE_VARIABLE_PATTERN)
    else:
        assert definition.parameters == ()


def test_server_status_uses_global_status_and_keeps_string_values() -> None:
    definition = build_inspection_query(ServerMetricsRequest(kind=ServerMetricKind.STATUS))

    assert definition.command is InspectionCommand.SERVER_STATUS
    assert definition.statement_type is SqlStatementType.SELECT
    assert "performance_schema.global_status" in definition.sql
    assert "performance_schema.global_variables" not in definition.sql
    assert "information_schema.GLOBAL_STATUS" not in definition.sql
    assert "AS redacted" not in definition.sql
    assert "CAST" not in definition.sql
    assert definition.parameters == CURATED_SERVER_STATUS_NAMES
    assert len(CURATED_SERVER_STATUS_NAMES) > 0
    predicate = definition.sql.split("WHERE", 1)[1]
    for name in CURATED_SERVER_STATUS_NAMES:
        assert name not in predicate


def test_server_status_filter_binds_a_like_pattern_without_interpolation() -> None:
    definition = build_inspection_query(
        ServerMetricsRequest(kind=ServerMetricKind.STATUS, filter_text="Threads")
    )

    assert "VARIABLE_NAME LIKE %s" in definition.sql
    assert "Threads" not in definition.sql
    assert definition.parameters == ("%Threads%",)


def test_sensitive_variable_markers_cover_required_markers() -> None:
    for marker in ("password", "secret", "token", "private_key", "ssl_key"):
        assert marker in SENSITIVE_VARIABLE_MARKERS
        assert marker in SENSITIVE_VARIABLE_PATTERN


def test_server_processes_default_redacts_info_and_binds_zero() -> None:
    definition = build_inspection_query(ServerProcessesRequest())

    assert definition.command is InspectionCommand.SERVER_PROCESSES
    assert definition.statement_type is SqlStatementType.SELECT
    assert "FROM performance_schema.processlist" in definition.sql
    assert "SHOW PROCESSLIST" not in definition.sql
    assert "SHOW FULL PROCESSLIST" not in definition.sql
    assert "information_schema.PROCESSLIST" not in definition.sql
    assert "CASE WHEN %s THEN INFO ELSE NULL END AS info" in definition.sql
    assert definition.parameters == (0,)
    assert definition.sql.count("%s") == len(definition.parameters)
    assert definition.sql.upper().endswith("ORDER BY ID")
    for alias in (
        "AS id",
        "AS user",
        "AS host",
        "AS `database`",
        "AS command",
        "AS time_seconds",
        "AS state",
        "AS info",
    ):
        assert alias in definition.sql
    for verb in ("BEGIN", "COMMIT", "ROLLBACK", "START TRANSACTION"):
        assert verb not in definition.sql.upper()


def test_server_processes_include_sql_binds_one_without_boolean_interpolation() -> None:
    definition = build_inspection_query(ServerProcessesRequest(include_sql=True))

    assert definition.command is InspectionCommand.SERVER_PROCESSES
    assert definition.parameters == (1,)
    assert "CASE WHEN %s THEN INFO ELSE NULL END AS info" in definition.sql
    assert "TRUE" not in definition.sql.upper()
    assert "FALSE" not in definition.sql.upper()


def test_server_metrics_request_validates_filter_and_all() -> None:
    with pytest.raises(ValueError):
        ServerMetricsRequest(kind=ServerMetricKind.VARIABLES, filter_text="buffer", all=True)
    with pytest.raises(ValueError):
        ServerMetricsRequest(kind=ServerMetricKind.STATUS, filter_text="   ")

    request = ServerMetricsRequest(kind=ServerMetricKind.VARIABLES, filter_text="  buffer  ")

    assert request.filter_text == "buffer"
