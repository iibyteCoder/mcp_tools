from datetime import datetime

import pytest

from mysql_client.enums import ExplainFormat, InputSource, OutputFormat, SqlStatementType
from mysql_client.models import (
    BenchmarkRequest,
    ColumnDefinition,
    DatabaseRow,
    ExecutionMetadata,
    ExecutionPolicyDefaults,
    QueryResult,
    ReadRequest,
    SqlInput,
    TargetMetadata,
)


def test_sql_input_preserves_source_without_io() -> None:
    sql = SqlInput.file("SELECT 1", "query.sql")

    assert sql.source is InputSource.FILE
    assert sql.name == "query.sql"
    assert sql.text == "SELECT 1"


def test_requests_are_frozen_and_validate_bounds() -> None:
    request = ReadRequest(sql=SqlInput.inline("SELECT 1"), page=2, page_size=25)

    assert request.page == 2
    with pytest.raises(ValueError, match="页码"):
        ReadRequest(sql=SqlInput.inline("SELECT 1"), page=0)
    with pytest.raises(ValueError, match="迭代"):
        BenchmarkRequest(sql=SqlInput.inline("SELECT 1"), iterations=0)


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
        result.has_more = True  # type: ignore[misc]


def test_policy_defaults_are_centralized_and_validated() -> None:
    defaults = ExecutionPolicyDefaults()

    assert defaults.page_size == 100
    assert defaults.max_page_size == 1_000
    with pytest.raises(ValueError, match="超时"):
        ExecutionPolicyDefaults(statement_timeout_seconds=0)


def test_enum_values_are_stable() -> None:
    assert ExplainFormat.JSON.value == "json"
    assert OutputFormat.CSV.value == "csv"
    assert SqlInput.inline("SELECT 1").source is InputSource.INLINE
