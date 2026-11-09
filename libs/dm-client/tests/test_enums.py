"""Contract checks for the closed DM client enums."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from enum import Enum

from dm_client.domain.enums import (
    KEY_SERVER_PARAMETERS,
    SENSITIVE_PARAMETER_MARKERS,
    SYSTEM_SCHEMAS,
    ComparisonDifferenceKind,
    ComparisonLocation,
    ComparisonSide,
    ConstraintType,
    ExecutionPolicy,
    InspectionKind,
    ObjectType,
    ParameterKey,
    PlanParseStatus,
    PolicyViolationReason,
    SensitiveParameterMarker,
    SqlParseReason,
    SqlReadEffect,
    SqlStatementType,
    SystemSchema,
    TransactionAction,
    WriteOutcome,
)

EXPECTED_VALUES: dict[type[Enum], set[str]] = {
    SqlStatementType: {
        "select",
        "insert",
        "update",
        "delete",
        "merge",
        "ddl",
        "show",
        "describe",
        "explain",
        "call",
        "set",
        "other",
    },
    ExecutionPolicy: {"read_only", "write", "explain", "analyze"},
    PolicyViolationReason: {
        "read_only_requires_read_statement",
        "write_requires_write_statement",
        "explain_requires_explainable_statement",
        "analyze_requires_table",
        "read_only_rejects_locking",
        "read_only_rejects_session_state",
    },
    SqlReadEffect: {"none", "locking", "session_state"},
    SqlParseReason: {
        "empty",
        "multiple_statements",
        "unterminated_quote",
        "unterminated_comment",
        "malformed",
    },
    TransactionAction: {"commit", "rollback"},
    WriteOutcome: {"committed", "rolled_back", "determined_failure", "unknown"},
    ObjectType: {
        "table",
        "view",
        "index",
        "sequence",
        "synonym",
        "procedure",
        "function",
        "package",
        "trigger",
    },
    ConstraintType: {"primary_key", "unique", "foreign_key", "check", "unknown"},
    ParameterKey: {
        "COMPATIBLE_MODE",
        "CASE_SENSITIVE",
        "JSON_MODE",
        "USE_JSON_DATATYPE",
        "BLANK_PAD_MODE",
        "LENGTH_IN_CHAR",
        "PAGE_SIZE",
        "EXTENT_SIZE",
        "BUFFER",
        "MAX_SESSIONS",
        "PORT_NUM",
        "INSTANCE_NAME",
    },
    SystemSchema: {"SYS", "SYSDBA", "SYSAUDITOR", "SYSSSO"},
    SensitiveParameterMarker: {"PWD", "PASSWORD", "PASSWD", "SECRET", "PRIVATE_KEY"},
    PlanParseStatus: {"parsed", "partial", "failed"},
    InspectionKind: {
        "server_inspect",
        "server_capabilities",
        "server_parameters",
        "schema_databases",
        "schema_tables",
        "schema_describe",
        "schema_indexes",
        "schema_stats",
        "schema_constraints",
        "schema_objects",
        "schema_ddl",
    },
    ComparisonDifferenceKind: {
        "column_definition",
        "row_count",
        "row_value",
        "key_column",
        "duplicate_key",
    },
    ComparisonLocation: {
        "columns",
        "rows.count",
        "row",
        "left.missing_key",
        "right.missing_key",
        "left.duplicate_key",
        "right.duplicate_key",
    },
    ComparisonSide: {"left", "right"},
}


@pytest.mark.parametrize(("enum_type", "expected"), EXPECTED_VALUES.items())
def test_enum_values_match_the_contract(enum_type: type[Enum], expected: set[str]) -> None:
    assert {member.value for member in enum_type} == expected
    assert enum_type.__doc__ is not None


@pytest.mark.parametrize("enum_type", EXPECTED_VALUES)
def test_enum_values_are_unique_and_json_serializable(enum_type: type[Enum]) -> None:
    values = [member.value for member in enum_type]

    assert len(values) == len(set(values))
    for value in values:
        assert json.loads(json.dumps(value)) == value


def test_named_constants_cover_their_enum() -> None:
    assert tuple(SystemSchema) == SYSTEM_SCHEMAS
    assert tuple(SensitiveParameterMarker) == SENSITIVE_PARAMETER_MARKERS
    assert tuple(ParameterKey) == KEY_SERVER_PARAMETERS
