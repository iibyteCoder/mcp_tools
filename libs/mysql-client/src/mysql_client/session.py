"""Explicitly managed, single-connection asynchronous MySQL session."""

from __future__ import annotations

import asyncio
import json
import statistics
import time
from contextlib import suppress
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, TypeVar, cast

from mysql_client.driver_adapter import (
    DriverFailure,
    QueryKiller,
    driver_failure_from_exception,
)
from mysql_client.enums import (
    ComparisonDifferenceKind,
    ComparisonLocation,
    ComparisonSide,
    DriverFailureKind,
    ExecutionPolicy,
    SqlStatementType,
    WriteOutcome,
)
from mysql_client.errors import (
    AuthenticationError,
    ClientError,
    ConnectionError,
    DatabaseNotFoundError,
    InvalidArgumentError,
    QueryCancelledError,
    QueryExecutionError,
    QueryTimeoutError,
    WriteExecutionError,
)
from mysql_client.inspection_queries import build_inspection_query
from mysql_client.parser import MySqlSqlParser
from mysql_client.policy import validate_execution_policy
from mysql_client.read_executor import ReadExecutor
from mysql_client.request_models import (
    BenchmarkRequest,
    CompareRequest,
    ExecutionPolicyDefaults,
    ExplainRequest,
    InspectionRequest,
    ReadRequest,
    SqlInput,
    WriteRequest,
)
from mysql_client.result_models import (
    BenchmarkResult,
    CompareResult,
    ComparisonDifference,
    ExecutionMetadata,
    ExplainResult,
    InspectionResult,
    QueryResult,
    TargetMetadata,
    WriteResult,
)
from mysql_client.write_executor import WriteExecutor

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from mysql_client.cancellation import CancellationToken
    from mysql_client.configuration import MySqlConnectionConfig
    from mysql_client.driver_adapter import DriverConnection, DriverFactory
    from mysql_client.enums import CancellationReason
    from mysql_client.value_models import DatabaseValue


class SessionState(str, Enum):
    """Lifecycle state of a non-pooled session."""

    NEW = "new"
    OPEN = "open"
    CLOSED = "closed"
    INVALIDATED = "invalidated"


_ResultT = TypeVar("_ResultT")


class MySqlSession:
    """One explicit async context around one database connection."""

    def __init__(
        self,
        config: MySqlConnectionConfig,
        driver_factory: DriverFactory,
        *,
        policy: ExecutionPolicyDefaults | None = None,
        cancellation: CancellationToken | None = None,
        target_label: str = "mysql",
    ) -> None:
        self._config = config
        self._driver_factory = driver_factory
        self._policy = policy or ExecutionPolicyDefaults()
        self._cancellation = cancellation
        self._target = TargetMetadata(
            label=target_label,
            host=config.host,
            port=config.port,
            database=config.database,
        )
        self._connection: DriverConnection | None = None
        self._state = SessionState.NEW
        self._read_executor = ReadExecutor(
            default_max_rows=self._policy.max_rows,
            default_max_bytes=self._policy.max_bytes,
        )
        self._write_executor = WriteExecutor()
        self._parser = MySqlSqlParser()

    @property
    def state(self) -> SessionState:
        return self._state

    async def __aenter__(self) -> MySqlSession:
        await self.connect()
        return self

    async def __aexit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        await self.close()

    async def connect(self) -> None:
        if self._state is SessionState.OPEN:
            return
        if self._state in {SessionState.CLOSED, SessionState.INVALIDATED}:
            raise ConnectionError("MySQL session 已关闭, 不能重新连接")
        try:
            self._connection = await asyncio.wait_for(
                self._driver_factory.connect(self._config),
                timeout=self._config.connect_timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            self._state = SessionState.INVALIDATED
            raise QueryTimeoutError("建立 MySQL 连接超时") from exc
        except DriverFailure as exc:
            self._state = SessionState.INVALIDATED
            raise self._client_error(exc, operation="connect") from exc
        except BaseException as exc:
            self._state = SessionState.INVALIDATED
            failure = driver_failure_from_exception(exc, operation="connect")
            raise self._client_error(failure, operation="connect") from exc
        self._state = SessionState.OPEN

    async def close(self) -> None:
        connection = self._connection
        self._connection = None
        if connection is not None:
            with suppress(BaseException):
                await connection.close()
        if self._state is not SessionState.INVALIDATED:
            self._state = SessionState.CLOSED

    async def execute_read(self, request: ReadRequest) -> QueryResult:
        parsed = self._parser.parse(request.sql)
        validate_execution_policy(parsed, ExecutionPolicy.READ_ONLY)
        request = self._read_request_with_statement_type(request, parsed.statement_type)
        return await self._execute_read_request(request)

    async def _execute_read_request(self, request: ReadRequest) -> QueryResult:
        connection = self._require_connection()
        started_at = datetime.now(timezone.utc)
        started = time.perf_counter()
        metadata = self._metadata(request.statement_type, started_at, started)
        try:
            result = await self._run(
                self._read_executor.execute(connection, request, target=self._target, metadata=metadata),
                timeout=request.statement_timeout_seconds or self._policy.statement_timeout_seconds,
            )
        except DriverFailure as exc:
            if exc.kind in {
                DriverFailureKind.CONNECTION,
                DriverFailureKind.TIMEOUT,
                DriverFailureKind.CANCELLED,
            }:
                await self._invalidate()
            raise self._client_error(exc, operation="read") from exc
        except (QueryTimeoutError, QueryCancelledError):
            await self._invalidate()
            raise
        except BaseException as exc:
            failure = driver_failure_from_exception(exc, operation="read")
            if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
                await self._invalidate()
                raise QueryTimeoutError(self._timeout_message()) from exc
            if failure.kind in {
                DriverFailureKind.CONNECTION,
                DriverFailureKind.TIMEOUT,
                DriverFailureKind.CANCELLED,
            }:
                await self._invalidate()
            raise self._client_error(failure, operation="read") from exc
        return self._with_duration(result, started)

    async def execute_write(self, request: WriteRequest) -> WriteResult:
        connection = self._require_connection()
        parsed = self._parser.parse(request.sql)
        validate_execution_policy(parsed, ExecutionPolicy.WRITE)
        request = WriteRequest(
            sql=request.sql,
            parameters=request.parameters,
            statement_type=parsed.statement_type,
            transaction=request.transaction,
            statement_timeout_seconds=request.statement_timeout_seconds,
        )
        started_at = datetime.now(timezone.utc)
        started = time.perf_counter()
        metadata = self._metadata(request.statement_type, started_at, started)
        try:
            result = await self._run(
                self._write_executor.execute(connection, request, metadata=metadata),
                timeout=request.statement_timeout_seconds or self._policy.statement_timeout_seconds,
            )
        except WriteExecutionError as exc:
            if exc.write_outcome is WriteOutcome.UNKNOWN:
                await self._invalidate()
            raise
        except DriverFailure as exc:
            await self._invalidate()
            if exc.kind is DriverFailureKind.TIMEOUT:
                raise QueryTimeoutError(self._timeout_message(), write_outcome=WriteOutcome.UNKNOWN) from exc
            if exc.kind is DriverFailureKind.CANCELLED:
                raise QueryCancelledError(
                    "MySQL 写入已取消; 受影响连接已丢弃, 状态未知",
                    write_outcome=WriteOutcome.UNKNOWN,
                ) from exc
            raise self._client_error(exc, operation="write") from exc
        except QueryTimeoutError as exc:
            await self._invalidate()
            raise QueryTimeoutError(self._timeout_message(), write_outcome=WriteOutcome.UNKNOWN) from exc
        except QueryCancelledError as exc:
            await self._invalidate()
            raise QueryCancelledError(
                "MySQL 写入已取消; 受影响连接已丢弃, 状态未知",
                write_outcome=WriteOutcome.UNKNOWN,
            ) from exc
        except ClientError:
            raise
        except BaseException as exc:
            await self._invalidate()
            if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
                raise QueryTimeoutError(self._timeout_message(), write_outcome=WriteOutcome.UNKNOWN) from exc
            failure = driver_failure_from_exception(exc, operation="write")
            if failure.kind is DriverFailureKind.TIMEOUT:
                raise QueryTimeoutError(self._timeout_message(), write_outcome=WriteOutcome.UNKNOWN) from exc
            if failure.kind is DriverFailureKind.CANCELLED:
                raise QueryCancelledError(
                    "MySQL 写入已取消; 受影响连接已丢弃, 状态未知",
                    write_outcome=WriteOutcome.UNKNOWN,
                ) from exc
            raise self._client_error(failure, operation="write") from exc
        return self._with_duration(result, started)

    async def execute_explain(self, request: ExplainRequest) -> ExplainResult:
        parsed = self._parser.parse(request.sql)
        validate_execution_policy(parsed, ExecutionPolicy.EXPLAIN)
        read_request = ReadRequest(
            sql=request.sql,
            parameters=request.parameters,
            statement_timeout_seconds=request.statement_timeout_seconds,
            statement_type=SqlStatementType.EXPLAIN,
        )
        result = await self._execute_read_request(read_request)
        return ExplainResult(
            format=request.format,
            columns=result.columns,
            rows=result.rows,
            metadata=result.metadata,
        )

    async def execute_benchmark(self, request: BenchmarkRequest) -> BenchmarkResult:
        parsed = self._parser.parse(request.sql)
        validate_execution_policy(parsed, ExecutionPolicy.READ_ONLY)
        iterations = request.iterations or self._policy.benchmark_iterations
        warmup_iterations = request.warmup_iterations
        if warmup_iterations is None:
            warmup_iterations = self._policy.benchmark_warmup_iterations
        if iterations > self._policy.benchmark_max_iterations:
            raise InvalidArgumentError("benchmark 迭代次数超过上限")
        if warmup_iterations > self._policy.benchmark_max_warmup_iterations:
            raise InvalidArgumentError("benchmark 预热次数超过上限")

        started_at = datetime.now(timezone.utc)
        started = time.perf_counter()
        for _ in range(warmup_iterations):
            await self.execute_read(
                ReadRequest(
                    sql=request.sql,
                    parameters=request.parameters,
                    max_rows=1,
                    statement_timeout_seconds=request.statement_timeout_seconds,
                    statement_type=parsed.statement_type,
                )
            )

        samples: list[float] = []
        for _ in range(iterations):
            sample_started = time.perf_counter()
            await self.execute_read(
                ReadRequest(
                    sql=request.sql,
                    parameters=request.parameters,
                    max_rows=1,
                    statement_timeout_seconds=request.statement_timeout_seconds,
                    statement_type=parsed.statement_type,
                )
            )
            samples.append((time.perf_counter() - sample_started) * 1000)

        sample_values = tuple(samples)
        metadata = ExecutionMetadata(
            statement_type=parsed.statement_type,
            duration_ms=(time.perf_counter() - started) * 1000,
            row_count=0,
            target=self._target,
            started_at=started_at,
        )
        return BenchmarkResult(
            samples_ms=sample_values,
            metadata=metadata,
            iterations=iterations,
            warmup_iterations=warmup_iterations,
            minimum_ms=min(sample_values),
            maximum_ms=max(sample_values),
            average_ms=statistics.fmean(sample_values),
            median_ms=statistics.median(sample_values),
        )

    async def execute_inspection(self, request: InspectionRequest) -> InspectionResult:
        """Execute a centrally-defined read-only inspection query."""

        definition = build_inspection_query(request)
        result = await self.execute_read(
            ReadRequest(
                sql=SqlInput.inline(definition.sql),
                parameters=definition.parameters,
                statement_type=definition.statement_type,
            )
        )
        return InspectionResult(command=definition.command, query=result)

    async def execute_compare(self, request: CompareRequest) -> CompareResult:
        left_parsed = self._parser.parse(request.left_sql)
        right_parsed = self._parser.parse(request.right_sql)
        validate_execution_policy(left_parsed, ExecutionPolicy.READ_ONLY)
        validate_execution_policy(right_parsed, ExecutionPolicy.READ_ONLY)
        left = await self.execute_read(
            ReadRequest(
                sql=request.left_sql,
                parameters=request.left_parameters,
                statement_timeout_seconds=request.statement_timeout_seconds,
                statement_type=left_parsed.statement_type,
            )
        )
        right = await self.execute_read(
            ReadRequest(
                sql=request.right_sql,
                parameters=request.right_parameters,
                statement_timeout_seconds=request.statement_timeout_seconds,
                statement_type=right_parsed.statement_type,
            )
        )
        max_diff_samples = (
            self._policy.max_diff_samples if request.max_diff_samples is None else request.max_diff_samples
        )
        equal, differences = self._compare_results(left, right, request.key_columns, max_diff_samples)
        return CompareResult(equal=equal, left=left, right=right, differences=differences)

    @staticmethod
    def _read_request_with_statement_type(request: ReadRequest, statement_type: SqlStatementType) -> ReadRequest:
        return ReadRequest(
            sql=request.sql,
            parameters=request.parameters,
            max_rows=request.max_rows,
            max_bytes=request.max_bytes,
            statement_timeout_seconds=request.statement_timeout_seconds,
            statement_type=statement_type,
        )

    @staticmethod
    def _compare_results(
        left: QueryResult,
        right: QueryResult,
        key_columns: tuple[str, ...],
        max_diff_samples: int,
    ) -> tuple[bool, tuple[ComparisonDifference, ...]]:
        differences: list[ComparisonDifference] = []
        mismatch = False

        def add(kind: ComparisonDifferenceKind, location: ComparisonLocation) -> None:
            nonlocal mismatch
            mismatch = True
            if len(differences) < max_diff_samples:
                differences.append(ComparisonDifference(kind=kind, location=location))

        left_columns = tuple((column.name, column.type_name) for column in left.columns)
        right_columns = tuple((column.name, column.type_name) for column in right.columns)
        if left_columns != right_columns:
            add(ComparisonDifferenceKind.COLUMN_DEFINITION, ComparisonLocation.COLUMNS)
            return not mismatch, tuple(differences)

        if key_columns:
            left_indexes = MySqlSession._key_indexes(left, key_columns, add)
            right_indexes = MySqlSession._key_indexes(right, key_columns, add)
            if left_indexes is None or right_indexes is None:
                return not mismatch, tuple(differences)
            left_rows = MySqlSession._rows_by_key(left, left_indexes, add, ComparisonSide.LEFT)
            right_rows = MySqlSession._rows_by_key(right, right_indexes, add, ComparisonSide.RIGHT)
            if left_rows is None or right_rows is None:
                return not mismatch, tuple(differences)
            for key in left_rows:
                if key not in right_rows:
                    add(ComparisonDifferenceKind.ROW_VALUE, ComparisonLocation.RIGHT_MISSING_KEY)
                elif left_rows[key] != right_rows[key]:
                    add(ComparisonDifferenceKind.ROW_VALUE, ComparisonLocation.ROW)
            for key in right_rows:
                if key not in left_rows:
                    add(ComparisonDifferenceKind.ROW_VALUE, ComparisonLocation.LEFT_MISSING_KEY)
            return not mismatch, tuple(differences)

        if len(left.rows) != len(right.rows):
            add(ComparisonDifferenceKind.ROW_COUNT, ComparisonLocation.ROW_COUNT)
        for left_row, right_row in zip(left.rows, right.rows, strict=False):
            if left_row != right_row:
                add(ComparisonDifferenceKind.ROW_VALUE, ComparisonLocation.ROW)
                if len(differences) >= max_diff_samples:
                    break
        return not mismatch, tuple(differences)

    @staticmethod
    def _key_indexes(
        result: QueryResult,
        key_columns: tuple[str, ...],
        add: Callable[[ComparisonDifferenceKind, ComparisonLocation], None],
    ) -> tuple[int, ...] | None:
        indexes: list[int] = []
        column_names = tuple(column.name for column in result.columns)
        for name in key_columns:
            if name not in column_names:
                add(ComparisonDifferenceKind.KEY_COLUMN, ComparisonLocation.COLUMNS)
                return None
            indexes.append(column_names.index(name))
        return tuple(indexes)

    @staticmethod
    def _rows_by_key(
        result: QueryResult,
        indexes: tuple[int, ...],
        add: Callable[[ComparisonDifferenceKind, ComparisonLocation], None],
        side: ComparisonSide,
    ) -> dict[str, tuple[DatabaseValue, ...]] | None:
        rows: dict[str, tuple[DatabaseValue, ...]] = {}
        for row in result.rows:
            key_values = tuple(row.values[index] for index in indexes)
            key = json.dumps(key_values, default=str, sort_keys=True, ensure_ascii=False)
            if key in rows:
                duplicate_location = (
                    ComparisonLocation.LEFT_DUPLICATE_KEY
                    if side is ComparisonSide.LEFT
                    else ComparisonLocation.RIGHT_DUPLICATE_KEY
                )
                add(ComparisonDifferenceKind.DUPLICATE_KEY, duplicate_location)
                return None
            rows[key] = row.values
        return rows

    def _require_connection(self) -> DriverConnection:
        if self._state is not SessionState.OPEN or self._connection is None:
            raise ConnectionError("MySQL session 尚未建立连接")
        return self._connection

    async def _run(self, operation: Coroutine[None, None, _ResultT], *, timeout: float) -> _ResultT:
        if self._cancellation is not None:
            await self._cancellation.raise_if_cancelled()
        operation_task = asyncio.create_task(operation)
        cancellation_task: asyncio.Task[object] | None = None
        if self._cancellation is not None:
            cancellation_task = asyncio.create_task(self._cancellation.wait())
        wait_tasks: set[asyncio.Task[object]] = {cast_task(operation_task)}
        if cancellation_task is not None:
            wait_tasks.add(cancellation_task)
        try:
            done, _ = await asyncio.wait(wait_tasks, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
        except asyncio.CancelledError as exc:
            await self._abort_query()
            operation_task.cancel()
            await self._await_cancelled(operation_task)
            if cancellation_task is not None:
                cancellation_task.cancel()
                with suppress(asyncio.CancelledError):
                    await cancellation_task
            raise QueryCancelledError("查询已取消; 受影响连接已丢弃, 未自动重试") from exc
        if not done:
            await self._abort_query()
            operation_task.cancel()
            await self._await_cancelled(operation_task)
            raise QueryTimeoutError(self._timeout_message())
        if cancellation_task is not None and cancellation_task in done:
            reason = cast("CancellationReason", cancellation_task.result())
            await self._abort_query()
            operation_task.cancel()
            await self._await_cancelled(operation_task)
            raise QueryCancelledError(f"查询已取消 (原因: {reason.value})")
        if cancellation_task is not None:
            cancellation_task.cancel()
            with suppress(asyncio.CancelledError):
                await cancellation_task
        return operation_task.result()

    @staticmethod
    async def _await_cancelled(task: asyncio.Task[_ResultT]) -> None:
        with suppress(BaseException):
            await task

    async def _abort_query(self) -> None:
        connection = self._connection
        if connection is None:
            return
        thread_id = connection.thread_id
        if thread_id is not None and isinstance(self._driver_factory, QueryKiller):
            with suppress(BaseException):
                await asyncio.wait_for(
                    self._driver_factory.kill_query(self._config, thread_id),
                    timeout=self._config.read_timeout_seconds,
                )
        await self._invalidate()

    async def _invalidate(self) -> None:
        connection = self._connection
        self._connection = None
        self._state = SessionState.INVALIDATED
        if connection is not None:
            with suppress(BaseException):
                await connection.close()

    def _metadata(self, statement_type: SqlStatementType, started_at: datetime, started: float) -> ExecutionMetadata:
        return ExecutionMetadata(
            statement_type=statement_type,
            duration_ms=(time.perf_counter() - started) * 1000,
            target=self._target,
            started_at=started_at,
        )

    @staticmethod
    def _with_duration(result: _ResultT, started: float) -> _ResultT:
        duration = (time.perf_counter() - started) * 1000
        if isinstance(result, QueryResult):
            return cast(
                "_ResultT",
                QueryResult(
                    columns=result.columns,
                    rows=result.rows,
                    metadata=ExecutionMetadata(
                        statement_type=result.metadata.statement_type,
                        duration_ms=duration,
                        row_count=result.metadata.row_count,
                        target=result.metadata.target,
                        started_at=result.metadata.started_at,
                    ),
                    truncated=result.truncated,
                ),
            )
        if isinstance(result, WriteResult):
            return cast(
                "_ResultT",
                WriteResult(
                    affected_rows=result.affected_rows,
                    metadata=ExecutionMetadata(
                        statement_type=result.metadata.statement_type,
                        duration_ms=duration,
                        affected_rows=result.metadata.affected_rows,
                        target=result.metadata.target,
                        started_at=result.metadata.started_at,
                    ),
                    generated_values=result.generated_values,
                ),
            )
        return result

    @staticmethod
    def _timeout_message() -> str:
        return "MySQL 查询超时; 受影响连接已丢弃, 未自动重试"

    @staticmethod
    def _client_error(failure: DriverFailure, *, operation: str) -> ClientError:
        del operation
        if failure.kind is DriverFailureKind.AUTHENTICATION:
            return AuthenticationError("MySQL 认证失败")
        if failure.kind is DriverFailureKind.PARAMETER:
            return InvalidArgumentError("MySQL 参数无效")
        if failure.kind is DriverFailureKind.DATABASE_NOT_FOUND:
            return DatabaseNotFoundError("MySQL 数据库不存在或不可访问")
        if failure.kind is DriverFailureKind.CONNECTION:
            return ConnectionError("MySQL 连接失败")
        if failure.kind is DriverFailureKind.TIMEOUT:
            return QueryTimeoutError("MySQL 查询超时; 受影响连接已丢弃, 未自动重试")
        if failure.kind is DriverFailureKind.CANCELLED:
            return QueryCancelledError("MySQL 查询已取消; 受影响连接已丢弃, 未自动重试")
        return QueryExecutionError("MySQL 执行失败; 未知写入状态不会自动重试")


def cast_task(task: asyncio.Task[_ResultT]) -> asyncio.Task[object]:
    """Widen a task only for asyncio.wait's homogeneous task set."""

    return cast("asyncio.Task[object]", task)
