"""Repeated read-only timing measurements without rewriting the caller's SQL."""

from __future__ import annotations

import statistics
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Final

from dm_client.domain.enums import ExecutionPolicy, SqlStatementType
from dm_client.domain.errors import InvalidArgumentError
from dm_client.domain.requests import ReadRequest
from dm_client.domain.results import BenchmarkResult, ExecutionMetadata, TargetMetadata
from dm_client.execution.read import run_read
from dm_client.sql.policy import validate_execution_policy

if TYPE_CHECKING:
    from dm_client.domain.requests import BenchmarkRequest, ParsedSql
    from dm_client.ports.driver import DmConnection

DEFAULT_BENCHMARK_ITERATIONS: Final[int] = 5
DEFAULT_BENCHMARK_WARMUP_ITERATIONS: Final[int] = 1
MAX_BENCHMARK_ITERATIONS: Final[int] = 100
MAX_BENCHMARK_WARMUP_ITERATIONS: Final[int] = 10

_ITERATIONS_LIMIT_MESSAGE: Final[str] = (
    f"benchmark iterations must not exceed {MAX_BENCHMARK_ITERATIONS}"
)
_WARMUP_LIMIT_MESSAGE: Final[str] = (
    f"benchmark warmup iterations must not exceed {MAX_BENCHMARK_WARMUP_ITERATIONS}"
)


def run_benchmark(
    connection: DmConnection,
    request: BenchmarkRequest,
    parsed: ParsedSql,
    target_label: str,
    *,
    target: TargetMetadata | None = None,
) -> BenchmarkResult:
    """Run warmup and timed reads with the supplied SQL and return timings.

    The session validates the policy before calling this function; validating
    once here keeps direct execution safe without re-checking each iteration.
    Every iteration reuses the ordinary read path with ``max_rows=1``.
    """

    validate_execution_policy(parsed, ExecutionPolicy.READ_ONLY)
    iterations = request.iterations or DEFAULT_BENCHMARK_ITERATIONS
    warmup_iterations = (
        DEFAULT_BENCHMARK_WARMUP_ITERATIONS
        if request.warmup_iterations is None
        else request.warmup_iterations
    )
    if iterations > MAX_BENCHMARK_ITERATIONS:
        raise InvalidArgumentError(_ITERATIONS_LIMIT_MESSAGE)
    if warmup_iterations > MAX_BENCHMARK_WARMUP_ITERATIONS:
        raise InvalidArgumentError(_WARMUP_LIMIT_MESSAGE)

    resolved_target = target or TargetMetadata(
        label=target_label,
        schema=connection.current_schema,
        server_version=connection.server_version,
    )
    read_request = ReadRequest(
        sql=request.sql,
        parameters=request.parameters,
        max_rows=1,
        statement_timeout_seconds=request.statement_timeout_seconds,
    )

    started_at = datetime.now(timezone.utc)
    started = time.perf_counter()
    for _ in range(warmup_iterations):
        run_read(connection, read_request, parsed, target_label, target=resolved_target)

    samples: list[float] = []
    for _ in range(iterations):
        sample_started = time.perf_counter()
        run_read(connection, read_request, parsed, target_label, target=resolved_target)
        samples.append((time.perf_counter() - sample_started) * 1000)
    duration_ms = (time.perf_counter() - started) * 1000

    sample_values = tuple(samples)
    return BenchmarkResult(
        metadata=ExecutionMetadata(
            statement_type=SqlStatementType.SELECT,
            duration_ms=duration_ms,
            target=resolved_target,
            started_at=started_at,
        ),
        samples_ms=sample_values,
        iterations=iterations,
        warmup_iterations=warmup_iterations,
        minimum_ms=min(sample_values),
        maximum_ms=max(sample_values),
        average_ms=statistics.fmean(sample_values),
        median_ms=statistics.median(sample_values),
    )


__all__ = [
    "DEFAULT_BENCHMARK_ITERATIONS",
    "DEFAULT_BENCHMARK_WARMUP_ITERATIONS",
    "MAX_BENCHMARK_ITERATIONS",
    "MAX_BENCHMARK_WARMUP_ITERATIONS",
    "run_benchmark",
]
