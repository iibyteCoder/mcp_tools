"""Unit tests for DmSession lifecycle, thread affinity and policy gates."""

from __future__ import annotations

import threading
from datetime import datetime
from typing import TYPE_CHECKING

import pytest

from dm_client.domain.configuration import DmConnectionConfig, SecretValue
from dm_client.domain.enums import (
    ComparisonDifferenceKind,
    ComparisonLocation,
    SqlStatementType,
    TransactionAction,
    WriteOutcome,
)
from dm_client.domain.errors import (
    ConfigurationError,
    ExecutionPolicyError,
    QueryError,
    SqlParseError,
    UnsupportedSqlError,
)
from dm_client.domain.requests import (
    BenchmarkRequest,
    CompareRequest,
    ExplainRequest,
    ReadRequest,
    SchemaAnalyzeRequest,
    SqlInput,
    WriteRequest,
)
from dm_client.domain.results import BenchmarkResult, CompareResult, TargetMetadata
from dm_client.domain.values import SchemaName, TableName
from dm_client.execution.session import DmSession, DmSessionState
from dm_client.ports.driver import DriverColumn

if TYPE_CHECKING:
    from collections.abc import Sequence


class Recorder:
    def __init__(self) -> None:
        self.threads: list[int] = []
        self.events: list[str] = []

    def record(self, event: str) -> None:
        self.threads.append(threading.get_ident())
        self.events.append(event)


class FakeCursor:
    def __init__(self, recorder: Recorder) -> None:
        self._recorder = recorder
        self.executed: list[tuple[str, Sequence[object]]] = []
        self._rows: Sequence[Sequence[object]] = ()
        self.fail_execute = False

    @property
    def description(self) -> Sequence[DriverColumn]:
        self._recorder.record("description")
        return (DriverColumn(name="N", type_name="NUMBER", nullable=False),)

    @property
    def rowcount(self) -> int:
        self._recorder.record("rowcount")
        return 1

    def execute(self, sql: str, parameters: tuple[object, ...] = ()) -> None:
        self._recorder.record("execute")
        self.executed.append((sql, parameters))
        if "SELECT 1" in sql:
            self._rows = ((1,),)
        elif "SELECT 2" in sql:
            self._rows = ((2,),)
        elif "FROM ALL_TAB_STATISTICS" in sql:
            self._rows = ((5, datetime(2026, 11, 8, 18, 30)),)
        else:
            self._rows = ()
        if self.fail_execute:
            raise QueryError("execute failed")

    def fetchmany(self, size: int) -> Sequence[Sequence[object]]:
        self._recorder.record("fetchmany")
        batch = self._rows[:size]
        self._rows = self._rows[size:]
        return batch

    def close(self) -> None:
        self._recorder.record("cursor.close")


class FakeConnection:
    def __init__(self, recorder: Recorder) -> None:
        self._recorder = recorder
        self._current_schema = "APP"
        self.fail_close = False
        self.closed = False
        self.commits = 0
        self.rollbacks = 0
        self.plan_text = "1   #NSET2: [1, 1, 1]"
        self.explained: list[str] = []

    @property
    def server_version(self) -> str:
        self._recorder.record("server_version")
        return "8.1.4.80"

    @property
    def current_schema(self) -> str:
        self._recorder.record("current_schema")
        return self._current_schema

    @property
    def str_case_sensitive(self) -> bool:
        return False

    @property
    def max_identifier_length(self) -> int:
        return 128

    def cursor(self) -> FakeCursor:
        self._recorder.record("cursor")
        return FakeCursor(self._recorder)

    def explain(self, sql: str) -> str:
        self._recorder.record("explain")
        self.explained.append(sql)
        return self.plan_text

    def commit(self) -> None:
        self._recorder.record("commit")
        self.commits += 1

    def rollback(self) -> None:
        self._recorder.record("rollback")
        self.rollbacks += 1

    def close(self) -> None:
        self._recorder.record("close")
        self.closed = True
        if self.fail_close:
            raise QueryError("close failed")


class FakeFactory:
    def __init__(self, connection: FakeConnection) -> None:
        self._connection = connection
        self._recorder = connection._recorder
        self.configs: list[DmConnectionConfig] = []

    def connect(self, config: DmConnectionConfig) -> FakeConnection:
        self._recorder.record("connect")
        self.configs.append(config)
        return self._connection


def config(**overrides: object) -> DmConnectionConfig:
    values: dict[str, object] = {
        "host": "127.0.0.1",
        "port": 15237,
        "user": "APP",
        "password": SecretValue(_value="secret"),
        "schema": SchemaName(value="APP"),
        "connect_timeout_seconds": 5.0,
        "query_timeout_seconds": 0.0,
    }
    values.update(overrides)
    return DmConnectionConfig(**values)  # type: ignore[arg-type]


def session_parts() -> tuple[Recorder, FakeConnection, FakeFactory]:
    recorder = Recorder()
    connection = FakeConnection(recorder)
    return recorder, connection, FakeFactory(connection)


@pytest.mark.asyncio
async def test_session_runs_every_driver_call_on_one_worker_thread() -> None:
    recorder, connection, factory = session_parts()

    async with DmSession(config(), factory, "test") as session:
        read = await session.execute_read(
            ReadRequest(sql=SqlInput.inline("SELECT 1 AS N FROM DUAL"))
        )
        committed = await session.execute_write(
            WriteRequest(
                sql=SqlInput.inline("INSERT INTO t (id) VALUES (?)"),
                parameters=(1,),
                transaction=TransactionAction.COMMIT,
            )
        )
        rolled_back = await session.execute_write(
            WriteRequest(
                sql=SqlInput.inline("INSERT INTO t (id) VALUES (?)"),
                parameters=(2,),
                transaction=TransactionAction.ROLLBACK,
            )
        )

    assert len(read.rows) == 1
    assert read.rows[0].values == (1,)
    assert read.metadata.target == TargetMetadata(
        label="test",
        host="127.0.0.1",
        port=15237,
        schema="APP",
        server_version="8.1.4.80",
    )
    assert committed.affected_rows == 1
    assert committed.outcome.value == "committed"
    assert rolled_back.outcome.value == "rolled_back"
    assert connection.commits == 1
    assert connection.rollbacks == 2
    assert connection.closed is True

    assert len(set(recorder.threads)) == 1
    assert recorder.threads[0] != threading.get_ident()
    for event in ("connect", "cursor", "execute", "fetchmany", "commit", "rollback", "close"):
        assert event in recorder.events


@pytest.mark.asyncio
async def test_session_rejects_schema_that_the_driver_did_not_apply() -> None:
    _, connection, factory = session_parts()
    session = DmSession(config(schema=SchemaName(value="OTHER")), factory, "test")

    with pytest.raises(ConfigurationError) as caught:
        await session.__aenter__()

    assert "OTHER" in str(caught.value)
    assert session.state is DmSessionState.FAILED
    assert connection.closed is True


@pytest.mark.asyncio
async def test_session_query_timeout_override_reaches_the_factory() -> None:
    _, _, factory = session_parts()

    async with DmSession(config(), factory, "test", query_timeout_seconds=12.5):
        pass

    assert factory.configs[0].query_timeout_seconds == 12.5


@pytest.mark.asyncio
async def test_session_rejects_writes_under_read_policy_before_driver_calls() -> None:
    recorder, _, factory = session_parts()

    async with DmSession(config(), factory, "test") as session:
        before = len(recorder.events)
        with pytest.raises(ExecutionPolicyError):
            await session.execute_read(
                ReadRequest(sql=SqlInput.inline("INSERT INTO t VALUES (1)"))
            )

    assert "execute" not in recorder.events[before:]


@pytest.mark.asyncio
async def test_session_rejects_parse_errors_before_driver_calls() -> None:
    recorder, _, factory = session_parts()

    async with DmSession(config(), factory, "test") as session:
        before = len(recorder.events)
        with pytest.raises(SqlParseError, match="not terminated"):
            await session.execute_read(
                ReadRequest(sql=SqlInput.inline("SELECT 'unterminated"))
            )

    assert "execute" not in recorder.events[before:]


@pytest.mark.asyncio
async def test_session_does_not_mask_the_primary_exception_on_cleanup() -> None:
    _, connection, factory = session_parts()
    connection.fail_close = True

    with pytest.raises(ValueError, match="body failure"):
        async with DmSession(config(), factory, "test"):
            raise ValueError("body failure")


@pytest.mark.asyncio
async def test_session_execute_explain_runs_on_the_worker_thread_without_executing() -> None:
    recorder, connection, factory = session_parts()

    async with DmSession(config(), factory, "test") as session:
        result = await session.execute_explain(
            ExplainRequest(sql=SqlInput.inline("EXPLAIN SELECT 1 FROM DUAL"))
        )

    assert connection.explained == ["SELECT 1 FROM DUAL"]
    assert result.plan_text == "1   #NSET2: [1, 1, 1]"
    assert [node.operation for node in result.nodes] == ["NSET2"]
    assert result.metadata.target == TargetMetadata(
        label="test",
        host="127.0.0.1",
        port=15237,
        schema="APP",
        server_version="8.1.4.80",
    )
    assert "execute" not in recorder.events
    assert "explain" in recorder.events
    assert len(set(recorder.threads)) == 1


@pytest.mark.asyncio
async def test_session_rejects_explain_analyze_before_driver_calls() -> None:
    recorder, _, factory = session_parts()

    async with DmSession(config(), factory, "test") as session:
        before = len(recorder.events)
        with pytest.raises(UnsupportedSqlError):
            await session.execute_explain(
                ExplainRequest(sql=SqlInput.inline("EXPLAIN ANALYZE SELECT 1 FROM DUAL"))
            )

    assert "explain" not in recorder.events[before:]


@pytest.mark.asyncio
async def test_session_execute_maintenance_commits_the_analysis_on_the_worker_thread() -> None:
    recorder, connection, factory = session_parts()

    async with DmSession(config(), factory, "test") as session:
        result = await session.execute_maintenance(
            SchemaAnalyzeRequest(table=TableName(value="T"))
        )

    assert result.outcome is WriteOutcome.COMMITTED
    assert result.schema == "APP"
    assert result.table == "T"
    assert result.before.num_rows == 5
    assert result.after.num_rows == 5
    assert result.after.last_analyzed == datetime(2026, 11, 8, 18, 30)
    assert result.metadata.target == TargetMetadata(
        label="test",
        host="127.0.0.1",
        port=15237,
        schema="APP",
        server_version="8.1.4.80",
    )
    assert connection.commits == 1
    assert recorder.events.count("execute") == 3
    assert len(set(recorder.threads)) == 1


@pytest.mark.asyncio
async def test_session_execute_benchmark_runs_warmup_and_timed_reads_on_worker() -> None:
    recorder, _, factory = session_parts()

    async with DmSession(config(), factory, "test") as session:
        before = len(recorder.events)
        result = await session.execute_benchmark(
            BenchmarkRequest(
                sql=SqlInput.inline("SELECT 1 AS N FROM DUAL"),
                iterations=2,
                warmup_iterations=1,
            )
        )

    assert isinstance(result, BenchmarkResult)
    assert result.iterations == 2
    assert result.warmup_iterations == 1
    assert len(result.samples_ms) == 2
    assert result.minimum_ms <= result.average_ms <= result.maximum_ms
    assert result.minimum_ms <= result.median_ms <= result.maximum_ms
    assert result.metadata.statement_type is SqlStatementType.SELECT
    assert result.metadata.duration_ms >= 0.0
    assert result.metadata.target == TargetMetadata(
        label="test",
        host="127.0.0.1",
        port=15237,
        schema="APP",
        server_version="8.1.4.80",
    )
    executed = [event for event in recorder.events[before:] if event == "execute"]
    assert len(executed) == 3
    assert len(set(recorder.threads)) == 1


@pytest.mark.asyncio
async def test_session_rejects_benchmark_writes_before_driver_calls() -> None:
    recorder, _, factory = session_parts()

    async with DmSession(config(), factory, "test") as session:
        before = len(recorder.events)
        with pytest.raises(ExecutionPolicyError):
            await session.execute_benchmark(
                BenchmarkRequest(sql=SqlInput.inline("UPDATE t SET N = 1"))
            )

    assert "execute" not in recorder.events[before:]


@pytest.mark.asyncio
async def test_session_execute_compare_executes_both_sides_once_on_worker() -> None:
    recorder, _, factory = session_parts()

    async with DmSession(config(), factory, "test") as session:
        before = len(recorder.events)
        result = await session.execute_compare(
            CompareRequest(
                left_sql=SqlInput.inline("SELECT 1 AS ID FROM DUAL"),
                right_sql=SqlInput.inline("SELECT 2 AS ID FROM DUAL"),
            )
        )

    assert isinstance(result, CompareResult)
    assert result.equal is False
    assert result.left.row_count == 1
    assert result.right.row_count == 1
    assert len(result.differences) == 1
    assert result.differences[0].kind is ComparisonDifferenceKind.ROW_VALUE
    assert result.differences[0].location is ComparisonLocation.ROW
    assert result.metadata is not None
    assert result.metadata.target == TargetMetadata(
        label="test",
        host="127.0.0.1",
        port=15237,
        schema="APP",
        server_version="8.1.4.80",
    )
    executed = [event for event in recorder.events[before:] if event == "execute"]
    assert len(executed) == 2
    assert len(set(recorder.threads)) == 1


@pytest.mark.asyncio
async def test_session_rejects_compare_writes_before_driver_calls() -> None:
    recorder, _, factory = session_parts()

    async with DmSession(config(), factory, "test") as session:
        before = len(recorder.events)
        with pytest.raises(ExecutionPolicyError):
            await session.execute_compare(
                CompareRequest(
                    left_sql=SqlInput.inline("SELECT 1 AS ID FROM DUAL"),
                    right_sql=SqlInput.inline("DELETE FROM t"),
                )
            )

    assert "execute" not in recorder.events[before:]
