"""Application service for typed SQL execution commands."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeAlias

from mysql_cli.domain.command import CommandAction, CommandGroup, CommandRequest, CommandStatus
from mysql_cli.presentation.output import SqlCommandData
from mysql_client import (
    BenchmarkRequest,
    BenchmarkResult,
    CompareRequest,
    CompareResult,
    ComparisonError,
    ExplainRequest,
    ExplainResult,
    InvalidArgumentError,
    MySqlSession,
    QueryResult,
    ReadRequest,
    WriteRequest,
    WriteResult,
)
from mysql_client.adapters.aiomysql import AiomysqlDriverFactory

if TYPE_CHECKING:
    from mysql_cli.application.input import LoadedInputs
    from mysql_cli.application.profile import ProfileService
    from mysql_client.ports.driver import DriverFactory


SqlResult: TypeAlias = QueryResult | WriteResult | ExplainResult | BenchmarkResult | CompareResult


class SqlExecutionService:
    """Resolve one selected profile and execute exactly one SQL operation."""

    def __init__(self, profiles: ProfileService, driver_factory: DriverFactory | None = None) -> None:
        self._profiles = profiles
        self._driver_factory = driver_factory or AiomysqlDriverFactory()

    async def execute(self, request: CommandRequest, inputs: LoadedInputs) -> SqlCommandData:
        if request.group is not CommandGroup.SQL:
            raise ValueError("SQL service 只接受 sql 命令")
        selection = self._profiles.selection(request.selected_profile)
        config = self._profiles.connection_config(selection.profile)
        async with MySqlSession(
            config,
            self._driver_factory,
            target_label=selection.profile.name.value,
        ) as session:
            result = await self._execute_request(session, request, inputs)
        if isinstance(result, CompareResult) and not result.equal:
            raise ComparisonError(result.differences)
        return SqlCommandData(
            status=CommandStatus.COMPLETED,
            command_group=request.group,
            action=request.action,
            profile=selection.profile.name.value,
            result=result,
        )

    async def _execute_request(self, session: MySqlSession, request: CommandRequest, inputs: LoadedInputs) -> SqlResult:
        if request.action is CommandAction.COMPARE:
            return await session.execute_compare(self._compare_request(request, inputs))
        sql = inputs.sql
        if sql is None:
            raise InvalidArgumentError("SQL 输入缺失")
        parameters = () if inputs.parameters is None else inputs.parameters.bindings
        if request.action is CommandAction.READ:
            return await session.execute_read(
                ReadRequest(
                    sql=sql,
                    parameters=parameters,
                    max_rows=request.sql_max_rows,
                    max_bytes=request.sql_max_bytes,
                    statement_timeout_seconds=request.sql_timeout_seconds,
                )
            )
        if request.action is CommandAction.WRITE:
            return await session.execute_write(
                WriteRequest(
                    sql=sql,
                    parameters=parameters,
                    transaction=request.sql_transaction,
                    statement_timeout_seconds=request.sql_timeout_seconds,
                )
            )
        if request.action is CommandAction.EXPLAIN:
            return await session.execute_explain(
                ExplainRequest(
                    sql=sql,
                    parameters=parameters,
                    statement_timeout_seconds=request.sql_timeout_seconds,
                )
            )
        if request.action is CommandAction.BENCHMARK:
            return await session.execute_benchmark(
                BenchmarkRequest(
                    sql=sql,
                    parameters=parameters,
                    iterations=request.sql_iterations,
                    warmup_iterations=request.sql_warmup_iterations,
                    statement_timeout_seconds=request.sql_timeout_seconds,
                )
            )
        raise InvalidArgumentError("不支持的 SQL 命令")

    @staticmethod
    def _compare_request(request: CommandRequest, inputs: LoadedInputs) -> CompareRequest:
        left_sql = inputs.compare_left_sql
        right_sql = inputs.compare_right_sql
        if left_sql is None or right_sql is None:
            raise InvalidArgumentError("compare 必须提供左右两条 SQL")
        left_parameters = () if inputs.compare_left_parameters is None else inputs.compare_left_parameters.bindings
        right_parameters = () if inputs.compare_right_parameters is None else inputs.compare_right_parameters.bindings
        return CompareRequest(
            left_sql=left_sql,
            right_sql=right_sql,
            left_parameters=left_parameters,
            right_parameters=right_parameters,
            key_columns=request.compare_key_columns,
            max_diff_samples=request.compare_max_diff_samples,
            statement_timeout_seconds=request.sql_timeout_seconds,
        )


__all__ = ["SqlExecutionService"]
