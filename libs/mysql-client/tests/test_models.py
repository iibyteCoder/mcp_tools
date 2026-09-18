from datetime import datetime

import pytest

from mysql_client.enums import ExplainFormat, InputSource, SqlStatementType
from mysql_client.request_models import (
    BenchmarkRequest,
    CompareRequest,
    ExecutionPolicyDefaults,
    ReadRequest,
    SqlInput,
)
from mysql_client.result_models import (
    ColumnDefinition,
    DatabaseRow,
    ExecutionMetadata,
    QueryResult,
    TargetMetadata,
)


def test_sql_input_preserves_source_without_io() -> None:
    sql = SqlInput.file("SELECT 1", "query.sql")

    assert sql.source is InputSource.FILE
    assert sql.name == "query.sql"
    assert sql.text == "SELECT 1"


def test_read_request_uses_execution_limits_instead_of_pagination() -> None:
    request = ReadRequest(
        sql=SqlInput.inline("SELECT 1"),
        max_rows=25,
        max_bytes=4_096,
        statement_timeout_seconds=2.5,
    )

    assert request.max_rows == 25
    assert request.max_bytes == 4_096
    assert request.statement_timeout_seconds == 2.5
    with pytest.raises(ValueError, match="最大行数"):
        ReadRequest(sql=SqlInput.inline("SELECT 1"), max_rows=0)
    with pytest.raises(ValueError, match="超时"):
        ReadRequest(sql=SqlInput.inline("SELECT 1"), statement_timeout_seconds=0)
    with pytest.raises(ValueError, match="迭代"):
        BenchmarkRequest(sql=SqlInput.inline("SELECT 1"), iterations=0)


def test_compare_request_contains_two_sql_inputs_not_targets() -> None:
    request = CompareRequest(
        left_sql=SqlInput.inline("SELECT 1"),
        right_sql=SqlInput.file("SELECT 1", "optimized.sql"),
        key_columns=("id",),
        max_diff_samples=5,
    )

    assert request.left_sql.text == "SELECT 1"
    assert request.right_sql.name == "optimized.sql"
    assert request.key_columns == ("id",)


def test_result_models_are_typed_and_immutable() -> None:
    target = TargetMetadata(label="local", database="app")
    metadata = ExecutionMetadata(
        statement_type=SqlStatementType.SELECT,
        duration_ms=1.5,
        target=target,
        started_at=datetime(2026, 1, 1),
    )
    result = QueryResult(
        columns=(ColumnDefinition(name="id", type_name="INT", ordinal=1),),
        rows=(DatabaseRow.from_values((1,)),),
        metadata=metadata,
    )

    assert result.rows[0].values == (1,)
    with pytest.raises(AttributeError):
        result.truncated = True  # type: ignore[misc]


def test_policy_defaults_are_centralized_and_validated() -> None:
    defaults = ExecutionPolicyDefaults()

    assert defaults.max_rows == 10_000
    assert defaults.max_bytes == 1_048_576
    assert defaults.statement_timeout_seconds == 30.0
    with pytest.raises(ValueError, match="超时"):
        ExecutionPolicyDefaults(statement_timeout_seconds=0)


def test_enum_values_are_stable() -> None:
    assert ExplainFormat.JSON.value == "json"
    assert SqlInput.inline("SELECT 1").source is InputSource.INLINE
