"""Explicitly managed, single-connection asynchronous MySQL session."""

from __future__ import annotations

import asyncio
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
from mysql_client.enums import DriverFailureKind, SqlStatementType
from mysql_client.errors import (
    AuthenticationError,
    ClientError,
    ConnectionError,
    DatabaseNotFoundError,
    InvalidArgumentError,
    QueryCancelledError,
    QueryExecutionError,
    QueryTimeoutError,
    UnsupportedSqlError,
)
from mysql_client.read_executor import ReadExecutor
from mysql_client.request_models import (
    BenchmarkRequest,
    CompareRequest,
    ExecutionPolicyDefaults,
    ExplainRequest,
    ReadRequest,
    SqlInput,
    WriteRequest,
)
from mysql_client.result_models import (
    BenchmarkResult,
    CompareResult,
    ExecutionMetadata,
    ExplainResult,
    QueryResult,
    TargetMetadata,
    WriteResult,
)
from mysql_client.write_executor import WriteExecutor

if TYPE_CHECKING:
    from collections.abc import Coroutine

    from mysql_client.cancellation import CancellationToken
    from mysql_client.configuration import MySqlConnectionConfig
    from mysql_client.driver_adapter import DriverConnection, DriverFactory
    from mysql_client.enums import CancellationReason


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
        started_at = datetime.now(timezone.utc)
        started = time.perf_counter()
        metadata = self._metadata(request.statement_type, started_at, started)
        try:
            result = await self._run(
                self._write_executor.execute(connection, request, metadata=metadata),
                timeout=request.statement_timeout_seconds or self._policy.statement_timeout_seconds,
            )
        except DriverFailure as exc:
            await self._invalidate()
            raise self._client_error(exc, operation="write") from exc
        except (QueryTimeoutError, QueryCancelledError):
            await self._invalidate()
            raise
        except BaseException as exc:
            await self._invalidate()
            if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
                raise QueryTimeoutError(self._timeout_message()) from exc
            failure = driver_failure_from_exception(exc, operation="write")
            raise self._client_error(failure, operation="write") from exc
        return self._with_duration(result, started)

    async def execute_explain(self, request: ExplainRequest) -> ExplainResult:
        prefix = "EXPLAIN"
        if request.analyze:
            prefix += " ANALYZE"
        elif request.format.value != "traditional":
            prefix += f" FORMAT={request.format.value.upper()}"
        read_request = ReadRequest(
            sql=SqlInput.inline(f"{prefix} {request.sql.text}"),
            parameters=request.parameters,
            statement_timeout_seconds=request.statement_timeout_seconds,
            statement_type=SqlStatementType.EXPLAIN,
        )
        result = await self.execute_read(read_request)
        return ExplainResult(
            format=request.format,
            columns=result.columns,
            rows=result.rows,
            metadata=result.metadata,
        )

    async def execute_benchmark(self, request: BenchmarkRequest) -> BenchmarkResult:
        del request
        raise UnsupportedSqlError("benchmark 不属于 mysql-client session 的基础执行能力")

    async def execute_compare(self, request: CompareRequest) -> CompareResult:
        del request
        raise UnsupportedSqlError("compare 不属于 mysql-client session 的基础执行能力")

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
        with suppress(asyncio.CancelledError):
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
