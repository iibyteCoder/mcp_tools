"""Unit tests for repeated benchmark execution and its bounds."""

from __future__ import annotations

import statistics
from typing import TYPE_CHECKING

import pytest

from dm_client.domain.enums import SqlStatementType
from dm_client.domain.errors import ExecutionPolicyError, InvalidArgumentError
from dm_client.domain.requests import BenchmarkRequest, SqlInput
from dm_client.domain.results import ExecutionMetadata, QueryResult, TargetMetadata
from dm_client.execution import benchmark as benchmark_module
from dm_client.execution.benchmark import (
    DEFAULT_BENCHMARK_ITERATIONS,
    DEFAULT_BENCHMARK_WARMUP_ITERATIONS,
    MAX_BENCHMARK_ITERATIONS,
    MAX_BENCHMARK_WARMUP_ITERATIONS,
    run_benchmark,
)
from dm_client.sql.parser import DmSqlParser

if TYPE_CHECKING:
    from dm_client.domain.requests import ParsedSql, ReadRequest
    from dm_client.ports.driver import DmConnection

TARGET = TargetMetadata(
    label="test",
    host="127.0.0.1",
    port=15237,
    schema="APP",
    server_version="8.1.4.80",
)


class FakeConnection:
    """Only the identity attributes unused when an explicit target is supplied."""

    current_schema = "APP"
    server_version = "8.1.4.80"


class ReadRecorder:
    def __init__(self) -> None:
        self.calls: list[ReadRequest] = []

    def __call__(
        self,
        connection: DmConnection,
        request: ReadRequest,
        parsed: ParsedSql,
        target_label: str,
        *,
        target: TargetMetadata | None = None,
    ) -> QueryResult:
        del connection, parsed, target_label, target
        self.calls.append(request)
        return QueryResult(
            columns=(),
            rows=(),
            metadata=ExecutionMetadata(
                statement_type=SqlStatementType.SELECT,
                duration_ms=0.0,
            ),
        )


def parsed_for(sql: str) -> ParsedSql:
    return DmSqlParser().parse(SqlInput.inline(sql))


def test_benchmark_uses_defaults_and_reports_statistics(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = ReadRecorder()
    monkeypatch.setattr(benchmark_module, "run_read", recorder)
    request = BenchmarkRequest(sql=SqlInput.inline("SELECT 1 AS N FROM DUAL"))

    result = run_benchmark(
        FakeConnection(),
        request,
        parsed_for("SELECT 1 AS N FROM DUAL"),
        "test",
        target=TARGET,
    )

    assert result.iterations == DEFAULT_BENCHMARK_ITERATIONS
    assert result.warmup_iterations == DEFAULT_BENCHMARK_WARMUP_ITERATIONS
    assert len(result.samples_ms) == DEFAULT_BENCHMARK_ITERATIONS
    assert len(recorder.calls) == DEFAULT_BENCHMARK_ITERATIONS + DEFAULT_BENCHMARK_WARMUP_ITERATIONS
    for call in recorder.calls:
        assert call.sql is request.sql
        assert call.parameters == ()
        assert call.max_rows == 1
        assert call.statement_timeout_seconds is None
    assert result.minimum_ms == min(result.samples_ms)
    assert result.maximum_ms == max(result.samples_ms)
    assert result.average_ms == statistics.fmean(result.samples_ms)
    assert result.median_ms == statistics.median(result.samples_ms)
    assert result.metadata.statement_type is SqlStatementType.SELECT
    assert result.metadata.target == TARGET
    assert result.metadata.duration_ms >= 0.0


def test_benchmark_honors_explicit_iterations_and_zero_warmup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = ReadRecorder()
    monkeypatch.setattr(benchmark_module, "run_read", recorder)
    request = BenchmarkRequest(
        sql=SqlInput.inline("SELECT 1 AS N FROM DUAL"),
        iterations=2,
        warmup_iterations=0,
        parameters=(1,),
    )

    result = run_benchmark(
        FakeConnection(),
        request,
        parsed_for("SELECT 1 AS N FROM DUAL"),
        "test",
        target=TARGET,
    )

    assert result.iterations == 2
    assert result.warmup_iterations == 0
    assert len(result.samples_ms) == 2
    assert len(recorder.calls) == 2
    assert all(call.parameters == (1,) for call in recorder.calls)


@pytest.mark.parametrize(
    ("iterations", "warmup_iterations"),
    [
        (MAX_BENCHMARK_ITERATIONS + 1, None),
        (None, MAX_BENCHMARK_WARMUP_ITERATIONS + 1),
        (1, MAX_BENCHMARK_WARMUP_ITERATIONS + 1),
    ],
)
def test_benchmark_rejects_values_above_the_limits(
    monkeypatch: pytest.MonkeyPatch,
    iterations: int | None,
    warmup_iterations: int | None,
) -> None:
    recorder = ReadRecorder()
    monkeypatch.setattr(benchmark_module, "run_read", recorder)
    request = BenchmarkRequest(
        sql=SqlInput.inline("SELECT 1 AS N FROM DUAL"),
        iterations=iterations,
        warmup_iterations=warmup_iterations,
    )

    with pytest.raises(InvalidArgumentError):
        run_benchmark(
            FakeConnection(),
            request,
            parsed_for("SELECT 1 AS N FROM DUAL"),
            "test",
            target=TARGET,
        )

    assert recorder.calls == []


def test_benchmark_rejects_non_read_statements(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = ReadRecorder()
    monkeypatch.setattr(benchmark_module, "run_read", recorder)
    sql = "UPDATE t SET N = 1"
    request = BenchmarkRequest(sql=SqlInput.inline(sql))

    with pytest.raises(ExecutionPolicyError):
        run_benchmark(FakeConnection(), request, parsed_for(sql), "test", target=TARGET)

    assert recorder.calls == []


def test_benchmark_read_request_carries_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = ReadRecorder()
    monkeypatch.setattr(benchmark_module, "run_read", recorder)
    request = BenchmarkRequest(
        sql=SqlInput.inline("SELECT 1 AS N FROM DUAL"),
        iterations=1,
        warmup_iterations=0,
        statement_timeout_seconds=2.5,
    )

    run_benchmark(
        FakeConnection(),
        request,
        parsed_for("SELECT 1 AS N FROM DUAL"),
        "test",
        target=TARGET,
    )

    assert recorder.calls[0].statement_timeout_seconds == 2.5


def test_benchmark_samples_are_plain_numbers(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = ReadRecorder()
    monkeypatch.setattr(benchmark_module, "run_read", recorder)
    request = BenchmarkRequest(sql=SqlInput.inline("SELECT 1 AS N FROM DUAL"))

    result = run_benchmark(
        FakeConnection(),
        request,
        parsed_for("SELECT 1 AS N FROM DUAL"),
        "test",
        target=TARGET,
    )

    for sample in result.samples_ms:
        assert isinstance(sample, float)
        assert sample >= 0.0
