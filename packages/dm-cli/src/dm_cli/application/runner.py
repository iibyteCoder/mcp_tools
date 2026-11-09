"""Framework-neutral command orchestration for the Dameng CLI boundary."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Final, Protocol

from dm_cli.application.actual_plan import actual_plan_diagnostic_sql
from dm_cli.application.errors import CliFailure, ErrorDetail
from dm_cli.application.input import (
    COMPARE_LEFT_SQL_ARGUMENT,
    COMPARE_RIGHT_SQL_ARGUMENT,
    COMPARE_SQL_ARGUMENT,
    SQL_INPUT_ARGUMENT,
    LoadedInputs,
    ParameterDocument,
    load_inputs,
)
from dm_cli.application.profile import ProfileServiceError, ProfileServiceErrorCode
from dm_cli.application.profile_commands import execute_profile_command
from dm_cli.application.results import (
    CommandData,
    CommandDiagnosticData,
    ComparisonDiagnostic,
    ParameterDiagnostic,
    ProfileCommandData,
    SqlDiagnostic,
)
from dm_cli.domain.command import (
    CommandAction,
    CommandGroup,
    CommandRequest,
    DiagnosticErrorType,
    DiagnosticStatus,
    ErrorCode,
    ExitCode,
    InputSource,
    SqlInputSpec,
)
from dm_client import (
    DmSqlParser,
    ExecutionPolicy,
    ParsedSql,
    SqlInput,
    SqlParseError,
    UnsupportedSqlError,
    validate_execution_policy,
)

if TYPE_CHECKING:
    from dm_cli.application.profile import ProfileService
    from dm_cli.application.results import InspectionCommandData, SqlCommandData
    from dm_cli.domain.profile import ProfileName


class SqlExecutor(Protocol):
    """Typed SQL service dependency used by command orchestration."""

    async def execute(self, request: CommandRequest, inputs: LoadedInputs) -> SqlCommandData: ...


class InspectionExecutor(Protocol):
    """Typed inspection service dependency used by command orchestration."""

    async def execute(self, request: CommandRequest) -> InspectionCommandData: ...


class ActualPlanExecutor(Protocol):
    """Typed actual-plan service dependency used by command orchestration."""

    async def execute(self, request: CommandRequest, inputs: LoadedInputs) -> SqlCommandData: ...


_SCHEMA_CATALOG_ACTIONS: Final[frozenset[CommandAction]] = frozenset(
    {CommandAction.DDL, CommandAction.CONSTRAINTS, CommandAction.OBJECTS}
)

_SCHEMA_MAINTENANCE_ACTIONS: Final[frozenset[CommandAction]] = frozenset({CommandAction.ANALYZE})


@dataclass(slots=True)
class CliRuntime:
    """Mutable invocation state kept outside the Click command callbacks."""

    profile_service: ProfileService
    sql_service: SqlExecutor | None = None
    actual_plan_service: ActualPlanExecutor | None = None
    server_inspection_service: InspectionExecutor | None = None
    schema_inspection_service: InspectionExecutor | None = None
    schema_catalog_service: InspectionExecutor | None = None
    schema_maintenance_service: InspectionExecutor | None = None
    selected_profile: ProfileName | None = None
    request: CommandRequest | None = None

    @classmethod
    def create_default(cls) -> CliRuntime:
        """Build the production composition without contacting a database."""

        from dm_cli.composition import create_runtime

        return create_runtime()


def request_requires_stdin(request: CommandRequest) -> bool:
    """Return whether the command needs one SQL document from standard input."""

    return request.sql_input is not None and request.sql_input.source is InputSource.STDIN


async def execute_request(runtime: CliRuntime, request: CommandRequest, *, stdin_text: str | None) -> CommandData:
    """Execute one validated request or return its parse-only diagnostic result."""

    if request.selected_profile is None and runtime.selected_profile is not None:
        request = replace(request, selected_profile=runtime.selected_profile)
    runtime.request = request

    if request.group is CommandGroup.PROFILE:
        result: ProfileCommandData = await execute_profile_command(request, runtime.profile_service)
        return result
    if request.group is CommandGroup.SERVER:
        return await _execute_inspection(runtime.server_inspection_service, request)
    if request.group is CommandGroup.SCHEMA:
        if request.action in _SCHEMA_MAINTENANCE_ACTIONS:
            return await _execute_inspection(runtime.schema_maintenance_service, request)
        if request.action in _SCHEMA_CATALOG_ACTIONS:
            return await _execute_inspection(runtime.schema_catalog_service, request)
        return await _execute_inspection(runtime.schema_inspection_service, request)
    if request.group is not CommandGroup.SQL:
        raise RuntimeError("command group is not implemented in this batch")

    loaded = load_inputs(request, stdin_text=stdin_text)
    diagnostic = diagnose(request, loaded)
    if request.selected_profile is not None:
        return await _execute_sql(runtime, request, loaded)
    if not _directory_selection_exists(runtime):
        return diagnostic
    return await _execute_sql(runtime, request, loaded)


def _directory_selection_exists(runtime: CliRuntime) -> bool:
    """Return whether the working directory binds a usable profile."""

    try:
        runtime.profile_service.selection(None)
    except ProfileServiceError as exc:
        if exc.code is ProfileServiceErrorCode.NOT_FOUND:
            return False
        raise
    return True


async def _execute_sql(runtime: CliRuntime, request: CommandRequest, loaded: LoadedInputs) -> SqlCommandData:
    if _uses_actual_plan(request):
        if runtime.actual_plan_service is None:
            raise RuntimeError("actual plan service is not configured")
        return await runtime.actual_plan_service.execute(request, loaded)
    if runtime.sql_service is None:
        raise RuntimeError("SQL service is not configured")
    return await runtime.sql_service.execute(request, loaded)


async def _execute_inspection(
    service: InspectionExecutor | None,
    request: CommandRequest,
) -> InspectionCommandData:
    if service is None:
        raise RuntimeError("inspection service is not configured")
    return await service.execute(request)


def diagnose(request: CommandRequest, loaded: LoadedInputs) -> CommandDiagnosticData:
    """Parse and classify SQL without selecting or contacting a database."""

    sql_diagnostic: SqlDiagnostic | None = None
    comparison_diagnostic: ComparisonDiagnostic | None = None
    if request.action is CommandAction.COMPARE:
        comparison_diagnostic = _comparison_diagnostic(request, loaded)
    elif loaded.sql is not None:
        if _uses_actual_plan(request):
            parsed = actual_plan_diagnostic_sql(request, loaded.sql)
        else:
            parsed = _parse_and_validate_sql(
                loaded.sql,
                policy=_policy_for_action(request.action),
                input_spec=request.sql_input,
                argument=SQL_INPUT_ARGUMENT,
            )
        sql_diagnostic = _sql_diagnostic(parsed, request.sql_input)
    parameter_diagnostic = _parameter_diagnostic(loaded.parameters)
    return CommandDiagnosticData(
        status=DiagnosticStatus.PARSED,
        command_group=request.group,
        action=request.action,
        sql=sql_diagnostic,
        parameters=parameter_diagnostic,
        comparison=comparison_diagnostic,
    )


def _comparison_diagnostic(request: CommandRequest, loaded: LoadedInputs) -> ComparisonDiagnostic:
    left = loaded.compare_left_sql
    right = loaded.compare_right_sql
    if left is None or right is None:
        raise _sql_failure(
            code=ErrorCode.INVALID_ARGUMENT,
            message="compare requires both left and right SQL input",
            error_type=DiagnosticErrorType.MISSING_SQL,
            input_spec=None,
            argument=COMPARE_SQL_ARGUMENT,
        )
    left_parsed = _parse_and_validate_sql(
        left,
        policy=ExecutionPolicy.READ_ONLY,
        input_spec=request.compare_left_sql_input,
        argument=COMPARE_LEFT_SQL_ARGUMENT,
    )
    right_parsed = _parse_and_validate_sql(
        right,
        policy=ExecutionPolicy.READ_ONLY,
        input_spec=request.compare_right_sql_input,
        argument=COMPARE_RIGHT_SQL_ARGUMENT,
    )
    return ComparisonDiagnostic(
        left=_sql_diagnostic(left_parsed, request.compare_left_sql_input),
        right=_sql_diagnostic(right_parsed, request.compare_right_sql_input),
    )


def _sql_diagnostic(parsed: ParsedSql, input_spec: SqlInputSpec | None) -> SqlDiagnostic:
    return SqlDiagnostic(
        source=input_spec.source if input_spec is not None else InputSource.INLINE,
        statement_type=parsed.statement_type,
        read_only=parsed.is_read_only,
        write=parsed.is_write,
        requires_explicit_transaction=parsed.requires_explicit_transaction,
        explain_analyze=parsed.is_explain_analyze,
        text_length=len(parsed.normalized_sql),
    )


def _parameter_diagnostic(parameters: ParameterDocument | None) -> ParameterDiagnostic | None:
    if parameters is None:
        return None
    return ParameterDiagnostic(
        source=InputSource.PARAMS_FILE,
        kind=parameters.kind,
        count=parameters.count,
        path=parameters.source,
    )


def _policy_for_action(action: CommandAction) -> ExecutionPolicy:
    if action in {CommandAction.READ, CommandAction.BENCHMARK, CommandAction.COMPARE}:
        return ExecutionPolicy.READ_ONLY
    if action is CommandAction.WRITE:
        return ExecutionPolicy.WRITE
    if action is CommandAction.EXPLAIN:
        return ExecutionPolicy.EXPLAIN
    raise ValueError("local SQL diagnostics support read, write, explain, benchmark and compare only")


def _parse_and_validate_sql(
    sql: SqlInput,
    *,
    policy: ExecutionPolicy,
    input_spec: SqlInputSpec | None,
    argument: str,
) -> ParsedSql:
    try:
        parsed = DmSqlParser().parse(sql)
    except SqlParseError as exc:
        raise _sql_failure(
            code=ErrorCode.INVALID_SQL,
            message=exc.message,
            error_type=DiagnosticErrorType.SQL_PARSE,
            input_spec=input_spec,
            argument=argument,
        ) from exc
    try:
        validate_execution_policy(parsed, policy)
    except UnsupportedSqlError as exc:
        # Includes policy mismatches and EXPLAIN ANALYZE rejections.
        raise _sql_failure(
            code=ErrorCode.UNSUPPORTED_SQL,
            message=exc.message,
            error_type=DiagnosticErrorType.POLICY_VIOLATION,
            input_spec=input_spec,
            argument=argument,
        ) from exc
    return parsed


def _uses_actual_plan(request: CommandRequest) -> bool:
    """Return whether the request asks for an executed autotrace plan."""

    return request.action is CommandAction.EXPLAIN and request.sql_explain_actual


def _sql_failure(
    *,
    code: ErrorCode,
    message: str,
    error_type: DiagnosticErrorType,
    input_spec: SqlInputSpec | None,
    argument: str,
) -> CliFailure:
    return CliFailure(
        code=code,
        message=message,
        retryable=False,
        details=(
            ErrorDetail(
                error_type=error_type,
                argument=argument,
                source=input_spec.source if input_spec is not None else None,
            ),
        ),
        exit_code=ExitCode.INVALID_ARGUMENT,
    )


__all__ = [
    "SQL_INPUT_ARGUMENT",
    "ActualPlanExecutor",
    "CliRuntime",
    "CommandData",
    "InspectionExecutor",
    "SqlExecutor",
    "diagnose",
    "execute_request",
    "request_requires_stdin",
]
