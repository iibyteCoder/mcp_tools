"""Unit tests for DM domain models and request validation."""

from __future__ import annotations

import math

import pytest

from dm_client.domain.configuration import (
    DEFAULT_DM_PORT,
    DEFAULT_LOGIN_TIMEOUT_SECONDS,
    DEFAULT_QUERY_TIMEOUT_SECONDS,
    DmConnectionConfig,
    SecretValue,
)
from dm_client.domain.enums import (
    ComparisonDifferenceKind,
    ComparisonLocation,
    ObjectType,
    SqlStatementType,
    TransactionAction,
    WriteOutcome,
)
from dm_client.domain.requests import (
    BenchmarkRequest,
    CompareRequest,
    ExplainRequest,
    ReadRequest,
    SchemaAnalyzeRequest,
    SchemaDdlRequest,
    SchemaDescribeRequest,
    SqlInput,
)
from dm_client.domain.results import (
    BenchmarkResult,
    ColumnDefinition,
    CompareResult,
    CompareSideSummary,
    ComparisonDifference,
    DatabaseRow,
    ExecutionMetadata,
    QueryResult,
)
from dm_client.domain.values import ObjectName, SchemaName, SqlText, TableName


def config(**overrides: object) -> DmConnectionConfig:
    values: dict[str, object] = {
        "host": "127.0.0.1",
        "user": "SYSDBA",
        "password": SecretValue(_value="top-secret"),
    }
    values.update(overrides)
    return DmConnectionConfig(**values)  # type: ignore[arg-type]


def metadata() -> ExecutionMetadata:
    return ExecutionMetadata(statement_type=SqlStatementType.SELECT, duration_ms=1.5)


def test_defaults_match_the_contract() -> None:
    value = config(schema=SchemaName(value="APP"))

    assert value.port == 5236 == DEFAULT_DM_PORT
    assert value.connect_timeout_seconds == 5.0 == DEFAULT_LOGIN_TIMEOUT_SECONDS
    assert value.query_timeout_seconds == 0.0 == DEFAULT_QUERY_TIMEOUT_SECONDS
    assert value.schema == SchemaName(value="APP")


def test_secret_value_never_reveals_itself_in_repr_or_str() -> None:
    secret = SecretValue(_value="top-secret")

    assert repr(secret) == "SecretValue(<redacted>)"
    assert str(secret) == "<redacted>"
    assert "top-secret" not in repr(config())
    assert secret.reveal() == "top-secret"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"host": " "}, "host"),
        ({"user": ""}, "user"),
        ({"port": 0}, "port"),
        ({"port": 65_536}, "port"),
        ({"port": True}, "port"),
        ({"connect_timeout_seconds": 0.0}, "connect timeout"),
        ({"connect_timeout_seconds": math.inf}, "connect timeout"),
        ({"query_timeout_seconds": -1.0}, "query timeout"),
        ({"query_timeout_seconds": math.nan}, "query timeout"),
    ],
)
def test_connection_config_rejects_invalid_values(overrides: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        config(**overrides)


def test_secret_value_rejects_empty_value() -> None:
    with pytest.raises(ValueError):
        SecretValue(_value="")


@pytest.mark.parametrize("value", ["A", "APP", "配置", "a.b", "x" * 128])
def test_identifier_values_accept_valid_names(value: str) -> None:
    assert SchemaName(value=value).value == value
    assert TableName(value=value).value == value
    assert ObjectName(value=value).value == value
    assert str(ObjectName(value=value)) == value


@pytest.mark.parametrize("value", ["", " ", "x" * 129, "bad\x00name"])
def test_identifier_values_reject_invalid_names(value: str) -> None:
    for identifier_type in (SchemaName, TableName, ObjectName):
        with pytest.raises(ValueError):
            identifier_type(value=value)


def test_sql_input_requires_non_empty_text() -> None:
    with pytest.raises(ValueError):
        SqlInput(text=SqlText(" "))
    assert SqlInput.inline("SELECT 1").name is None


@pytest.mark.parametrize(
    "build_request",
    [
        lambda: ReadRequest(sql=SqlInput.inline("SELECT 1"), max_rows=0),
        lambda: ReadRequest(sql=SqlInput.inline("SELECT 1"), max_bytes=0),
        lambda: ReadRequest(sql=SqlInput.inline("SELECT 1"), statement_timeout_seconds=0),
        lambda: BenchmarkRequest(sql=SqlInput.inline("SELECT 1"), iterations=0),
        lambda: BenchmarkRequest(sql=SqlInput.inline("SELECT 1"), warmup_iterations=-1),
        lambda: ExplainRequest(sql=SqlInput.inline("SELECT 1"), statement_timeout_seconds=-1),
        lambda: SchemaAnalyzeRequest(table=TableName(value="T"), estimate_percent=0),
        lambda: SchemaAnalyzeRequest(table=TableName(value="T"), estimate_percent=101),
        lambda: SchemaAnalyzeRequest(table=TableName(value="T"), degree=0),
        lambda: SchemaAnalyzeRequest(table=TableName(value="T"), partition=" "),
    ],
)
def test_requests_reject_invalid_bounds(build_request: object) -> None:
    assert callable(build_request)
    with pytest.raises(ValueError):
        build_request()


def test_typed_requests_and_results_compose() -> None:
    request = SchemaDdlRequest(
        object_type=ObjectType.TABLE,
        name=ObjectName(value="T"),
        schema=SchemaName(value="APP"),
    )
    describe = SchemaDescribeRequest(table=TableName(value="T"))
    result = QueryResult(
        columns=(ColumnDefinition(name="ID", type_name="INT"),),
        rows=(DatabaseRow.from_values((1,)),),
        metadata=metadata(),
    )
    benchmark = BenchmarkResult(metadata=metadata(), samples_ms=(0.5,), iterations=1)
    compare = CompareRequest(
        left_sql=SqlInput.inline("SELECT 1"),
        right_sql=SqlInput.inline("SELECT 1"),
        key_columns=("id",),
    )
    comparison = CompareResult(
        equal=False,
        left=CompareSideSummary(columns=result.columns, row_count=1),
        right=CompareSideSummary(columns=result.columns, row_count=1),
        differences=(
            ComparisonDifference(
                kind=ComparisonDifferenceKind.ROW_VALUE,
                location=ComparisonLocation.ROW,
                key_values=(1,),
            ),
        ),
    )

    assert request.object_type is ObjectType.TABLE
    assert describe.schema is None
    assert result.rows[0].values == (1,)
    assert benchmark.iterations == 1
    assert compare.key_columns == ("id",)
    assert comparison.differences[0].key_values == (1,)
    assert comparison.left.row_count == 1


def test_schema_analyze_defaults_to_cascade() -> None:
    request = SchemaAnalyzeRequest(table=TableName(value="T"))

    assert request.cascade is True


def test_write_request_carries_transaction_and_outcome_enums() -> None:
    assert TransactionAction.ROLLBACK.value == "rollback"
    assert WriteOutcome.UNKNOWN.value == "unknown"
