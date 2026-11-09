"""Explicitly managed, single-connection asynchronous DM session."""

from __future__ import annotations

from contextlib import suppress
from dataclasses import replace
from enum import Enum
from typing import TYPE_CHECKING

from dm_client.domain.enums import ExecutionPolicy
from dm_client.domain.errors import ConfigurationError, ConnectionError
from dm_client.execution.benchmark import run_benchmark
from dm_client.execution.compare import run_compare
from dm_client.execution.executor import DriverExecutor
from dm_client.execution.explain import run_explain
from dm_client.execution.inspection import run_inspection
from dm_client.execution.read import run_read
from dm_client.execution.schema_catalog import run_schema_ddl
from dm_client.execution.schema_maintenance import run_schema_analyze
from dm_client.execution.target import build_target
from dm_client.execution.write import run_write
from dm_client.sql.parser import DmSqlParser
from dm_client.sql.policy import validate_execution_policy

if TYPE_CHECKING:
    from dm_client.domain.configuration import DmConnectionConfig
    from dm_client.domain.requests import (
        BenchmarkRequest,
        CatalogRequest,
        CompareRequest,
        ExplainRequest,
        InspectionRequest,
        MaintenanceRequest,
        ReadRequest,
        WriteRequest,
    )
    from dm_client.domain.results import (
        AnalyzeResult,
        BenchmarkResult,
        CompareResult,
        DdlResult,
        ExplainResult,
        InspectionResponse,
        QueryResult,
        TargetMetadata,
        WriteResult,
    )
    from dm_client.ports.driver import DmConnection, DriverFactory


class DmSessionState(str, Enum):
    """Lifecycle state of one non-pooled DM session."""

    NEW = "new"
    OPEN = "open"
    CLOSED = "closed"
    FAILED = "failed"


class DmSession:
    """One async context around one dedicated-thread DM connection."""

    def __init__(
        self,
        config: DmConnectionConfig,
        driver_factory: DriverFactory,
        target_label: str | None = None,
        *,
        query_timeout_seconds: float | None = None,
    ) -> None:
        self._config = (
            replace(config, query_timeout_seconds=query_timeout_seconds)
            if query_timeout_seconds is not None
            else config
        )
        self._driver_factory = driver_factory
        self._target_label = target_label if target_label is not None else self._config.host
        self._executor: DriverExecutor | None = None
        self._connection: DmConnection | None = None
        self._target: TargetMetadata | None = None
        self._state = DmSessionState.NEW
        self._parser = DmSqlParser()

    @property
    def state(self) -> DmSessionState:
        return self._state

    async def __aenter__(self) -> DmSession:
        if self._state is DmSessionState.OPEN and self._connection is not None:
            return self
        if self._state in {DmSessionState.CLOSED, DmSessionState.FAILED}:
            raise ConnectionError("DM session is closed and cannot be reopened")

        executor = DriverExecutor()
        self._executor = executor
        connection: DmConnection | None = None
        try:
            connection = await executor.run(self._driver_factory.connect, self._config)
            cursor = await executor.run(connection.cursor)
            await executor.run(cursor.close)

            requested_schema = self._config.schema.value if self._config.schema is not None else None
            current_schema = await executor.run(_current_schema, connection)
            if requested_schema is not None and current_schema != requested_schema:
                raise ConfigurationError(
                    f"DM schema {requested_schema!r} was not applied; "
                    f"the connected schema is {current_schema!r}",
                    hint="verify that the schema exists and the user can access it",
                )
            target = await executor.run(build_target, self._target_label, self._config, connection)
        except BaseException:
            if connection is not None:
                with suppress(BaseException):
                    await executor.run(connection.close)
            self._connection = None
            self._target = None
            self._executor = None
            self._state = DmSessionState.FAILED
            executor.shutdown()
            raise

        self._connection = connection
        self._target = target
        self._state = DmSessionState.OPEN
        return self

    async def __aexit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        connection = self._connection
        executor = self._executor
        self._connection = None
        self._target = None
        self._executor = None
        self._state = DmSessionState.CLOSED
        if executor is None:
            return
        try:
            if connection is not None:
                with suppress(BaseException):
                    await executor.run(connection.rollback)
                try:
                    await executor.run(connection.close)
                except BaseException:
                    if exc_value is None:
                        raise
        finally:
            executor.shutdown()

    async def execute_read(self, request: ReadRequest) -> QueryResult:
        parsed = self._parser.parse(request.sql)
        validate_execution_policy(parsed, ExecutionPolicy.READ_ONLY)
        connection, executor = self._require_execution()
        return await executor.run(
            run_read,
            connection,
            request,
            parsed,
            self._target_label,
            target=self._target,
        )

    async def execute_write(self, request: WriteRequest) -> WriteResult:
        parsed = self._parser.parse(request.sql)
        validate_execution_policy(parsed, ExecutionPolicy.WRITE)
        connection, executor = self._require_execution()
        return await executor.run(
            run_write,
            connection,
            request,
            parsed,
            self._target_label,
            target=self._target,
        )

    async def execute_explain(self, request: ExplainRequest) -> ExplainResult:
        parsed = self._parser.parse(request.sql)
        validate_execution_policy(parsed, ExecutionPolicy.EXPLAIN)
        connection, executor = self._require_execution()
        return await executor.run(
            run_explain,
            connection,
            request,
            parsed,
            self._target_label,
            target=self._target,
        )

    async def execute_benchmark(self, request: BenchmarkRequest) -> BenchmarkResult:
        parsed = self._parser.parse(request.sql)
        validate_execution_policy(parsed, ExecutionPolicy.READ_ONLY)
        connection, executor = self._require_execution()
        return await executor.run(
            run_benchmark,
            connection,
            request,
            parsed,
            self._target_label,
            target=self._target,
        )

    async def execute_compare(self, request: CompareRequest) -> CompareResult:
        left_parsed = self._parser.parse(request.left_sql)
        right_parsed = self._parser.parse(request.right_sql)
        validate_execution_policy(left_parsed, ExecutionPolicy.READ_ONLY)
        validate_execution_policy(right_parsed, ExecutionPolicy.READ_ONLY)
        connection, executor = self._require_execution()
        return await executor.run(
            run_compare,
            connection,
            request,
            self._target_label,
            target=self._target,
        )

    async def execute_inspection(self, request: InspectionRequest) -> InspectionResponse:
        connection, executor = self._require_execution()
        return await executor.run(
            run_inspection,
            connection,
            request,
            self._target_label,
            target=self._target,
        )

    async def execute_catalog(self, request: CatalogRequest) -> DdlResult:
        connection, executor = self._require_execution()
        return await executor.run(
            run_schema_ddl,
            connection,
            request,
            self._target_label,
            target=self._target,
        )

    async def execute_maintenance(self, request: MaintenanceRequest) -> AnalyzeResult:
        connection, executor = self._require_execution()
        return await executor.run(
            run_schema_analyze,
            connection,
            request,
            self._target_label,
            target=self._target,
        )

    def _require_execution(self) -> tuple[DmConnection, DriverExecutor]:
        if self._state is not DmSessionState.OPEN or self._connection is None or self._executor is None:
            raise ConnectionError("DM session is not connected")
        return self._connection, self._executor


def _current_schema(connection: DmConnection) -> str:
    return connection.current_schema


__all__ = ["DmSession", "DmSessionState"]
