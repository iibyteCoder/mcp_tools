"""Application service for typed SQL execution commands."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeAlias

from dm_cli.application.results import SqlCommandData
from dm_cli.domain.command import CommandAction, CommandGroup, CommandRequest, CommandStatus
from dm_client import (
    BenchmarkRequest,
    BenchmarkResult,
    CompareRequest,
    CompareResult,
    ComparisonError,
    DmSession,
    ExplainRequest,
    ExplainResult,
    InvalidArgumentError,
    QueryResult,
    ReadRequest,
    WriteRequest,
    WriteResult,
)

if TYPE_CHECKING:
    from dm_cli.application.input import LoadedInputs
    from dm_cli.application.profile import ProfileService
    from dm_cli.domain.profile import ProfileRecord
    from dm_client import DatabaseParameters, DriverFactory


SqlResult: TypeAlias = QueryResult | WriteResult | ExplainResult | BenchmarkResult | CompareResult


class SqlExecutionService:
    """Resolve one selected profile and execute exactly one SQL operation."""

    def __init__(self, profiles: ProfileService, driver_factory: DriverFactory) -> None:
        self._profiles = profiles
        self._driver_factory = driver_factory

    async def execute(self, request: CommandRequest, inputs: LoadedInputs) -> SqlCommandData:
        if request.group is not CommandGroup.SQL:
            raise ValueError("SQL service accepts the sql command group only")
        _require_inputs(request, inputs)
        selection = self._profiles.selection(request.selected_profile)
        profile = selection.profile
        config = self._profiles.connection_config(profile)
        effective_timeout = _effective_timeout(request, profile)
        statement_timeout = _optional_statement_timeout(effective_timeout)

        async with DmSession(
            config,
            self._driver_factory,
            target_label=profile.name.value,
            query_timeout_seconds=effective_timeout,
        ) as session:
            result = await self._execute_request(session, request, inputs, statement_timeout)
        if isinstance(result, CompareResult) and not result.equal:
            raise ComparisonError(result.differences)
        return SqlCommandData(
            status=CommandStatus.COMPLETED,
            command_group=request.group,
            action=request.action,
            profile=profile.name.value,
            result=result,
        )

    async def _execute_request(
        self,
        session: DmSession,
        request: CommandRequest,
        inputs: LoadedInputs,
        statement_timeout: float | None,
    ) -> SqlResult:
        if request.action is CommandAction.COMPARE:
            return await session.execute_compare(_compare_request(request, inputs, statement_timeout))

        sql = inputs.sql
        if sql is None:
            raise InvalidArgumentError("SQL input is required")
        parameters: DatabaseParameters = () if inputs.parameters is None else inputs.parameters.bindings

        if request.action is CommandAction.READ:
            return await session.execute_read(
                ReadRequest(
                    sql=sql,
                    parameters=parameters,
                    max_rows=request.sql_max_rows,
                    max_bytes=request.sql_max_bytes,
                    statement_timeout_seconds=statement_timeout,
                )
            )
        if request.action is CommandAction.WRITE:
            return await session.execute_write(
                WriteRequest(
                    sql=sql,
                    parameters=parameters,
                    transaction=request.sql_transaction,
                    statement_timeout_seconds=statement_timeout,
                )
            )
        if request.action is CommandAction.EXPLAIN:
            return await session.execute_explain(
                ExplainRequest(sql=sql, statement_timeout_seconds=statement_timeout)
            )
        if request.action is CommandAction.BENCHMARK:
            return await session.execute_benchmark(
                BenchmarkRequest(
                    sql=sql,
                    parameters=parameters,
                    iterations=request.sql_iterations,
                    warmup_iterations=request.sql_warmup_iterations,
                    statement_timeout_seconds=statement_timeout,
                )
            )
        raise InvalidArgumentError("unsupported SQL action")


def _require_inputs(request: CommandRequest, inputs: LoadedInputs) -> None:
    """Reject missing inputs before a profile is selected or a connection opens."""

    if request.action is CommandAction.COMPARE:
        if inputs.compare_left_sql is None or inputs.compare_right_sql is None:
            raise InvalidArgumentError("compare requires both left and right SQL input")
        return
    if inputs.sql is None:
        raise InvalidArgumentError("SQL input is required")


def _compare_request(
    request: CommandRequest,
    inputs: LoadedInputs,
    statement_timeout: float | None,
) -> CompareRequest:
    left_sql = inputs.compare_left_sql
    right_sql = inputs.compare_right_sql
    if left_sql is None or right_sql is None:
        raise InvalidArgumentError("compare requires both left and right SQL input")
    left_parameters: DatabaseParameters = (
        () if inputs.compare_left_parameters is None else inputs.compare_left_parameters.bindings
    )
    right_parameters: DatabaseParameters = (
        () if inputs.compare_right_parameters is None else inputs.compare_right_parameters.bindings
    )
    return CompareRequest(
        left_sql=left_sql,
        right_sql=right_sql,
        left_parameters=left_parameters,
        right_parameters=right_parameters,
        key_columns=request.compare_key_columns,
        max_diff_samples=request.compare_max_diff_samples,
        statement_timeout_seconds=statement_timeout,
    )


def _effective_timeout(request: CommandRequest, profile: ProfileRecord) -> float:
    if request.sql_timeout_seconds is not None:
        return request.sql_timeout_seconds
    return profile.settings.query_timeout


def _optional_statement_timeout(seconds: float) -> float | None:
    """Map the profile convention of zero meaning unlimited to an absent bound."""

    return seconds if seconds > 0 else None


__all__ = ["SqlExecutionService"]
