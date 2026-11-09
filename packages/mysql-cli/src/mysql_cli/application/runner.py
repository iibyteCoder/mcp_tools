"""Framework-neutral command orchestration for the MySQL CLI boundary."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Protocol

from mysql_cli.application.errors import CliFailure, ErrorDetail
from mysql_cli.application.explain import build_explain_analyze
from mysql_cli.application.input import LoadedInputs, load_inputs
from mysql_cli.application.profile_commands import execute_profile_command
from mysql_cli.application.results import (
    CommandDiagnosticData,
    InspectionCommandData,
    ParameterDiagnostic,
    ProfileCommandData,
    SchemaAnalyzeCommandData,
    SqlCommandData,
    SqlDiagnostic,
)
from mysql_cli.domain.command import (
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
from mysql_client import (
    ClientError,
    ExecutionPolicy,
    ExecutionPolicyError,
    MySqlSqlParser,
    ParsedSql,
    SqlInput,
    SqlParseError,
    UnsupportedSqlError,
    validate_execution_policy,
)
from mysql_client import (
    ErrorCode as ClientErrorCode,
)

if TYPE_CHECKING:
    from db_cli_kit.profiles import ProfileName
    from mysql_cli.application.profile import ProfileService


CommandData = (
    CommandDiagnosticData
    | ProfileCommandData
    | InspectionCommandData
    | SchemaAnalyzeCommandData
    | SqlCommandData
)


class InspectionExecutor(Protocol):
    """Typed inspection service dependency used by command orchestration."""

    async def execute(self, request: CommandRequest) -> InspectionCommandData: ...


class SchemaMaintenanceExecutor(Protocol):
    """Typed schema maintenance service dependency used by command orchestration."""

    async def execute(self, request: CommandRequest) -> SchemaAnalyzeCommandData: ...


class SqlExecutor(Protocol):
    """Typed SQL service dependency used by command orchestration."""

    async def execute(self, request: CommandRequest, inputs: LoadedInputs) -> SqlCommandData: ...


@dataclass(slots=True)
class CliRuntime:
    """Mutable invocation state kept outside the Click command callbacks."""

    profile_service: ProfileService
    inspection_service: InspectionExecutor | None = None
    schema_maintenance_service: SchemaMaintenanceExecutor | None = None
    sql_service: SqlExecutor | None = None
    selected_profile: ProfileName | None = None
    request: CommandRequest | None = None

    @classmethod
    def create_default(cls) -> CliRuntime:
        """Build the production composition without contacting a database."""

        from mysql_cli.composition import create_runtime

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
        return await execute_profile_command(request, runtime.profile_service)
    if request.group is CommandGroup.SCHEMA and request.action is CommandAction.ANALYZE:
        if runtime.schema_maintenance_service is None:
            raise RuntimeError("schema maintenance service is not configured")
        return await runtime.schema_maintenance_service.execute(request)
    if request.group in {CommandGroup.SERVER, CommandGroup.SCHEMA}:
        if runtime.inspection_service is None:
            raise RuntimeError("inspection service is not configured")
        return await runtime.inspection_service.execute(request)
    if request.group is not CommandGroup.SQL:
        raise ValueError("unsupported command group")

    loaded = load_inputs(request, stdin_text=stdin_text)
    diagnostic = diagnose(request, loaded)
    if request.selected_profile is not None:
        if runtime.sql_service is None:
            raise RuntimeError("SQL service is not configured")
        return await runtime.sql_service.execute(request, loaded)
    return diagnostic


def diagnose(request: CommandRequest, loaded: LoadedInputs) -> CommandDiagnosticData:
    """Parse and classify SQL without selecting or contacting a database."""

    sql_diagnostic: SqlDiagnostic | None = None
    if request.action is CommandAction.COMPARE:
        _validate_compare_inputs(request, loaded)
    elif loaded.sql is not None:
        parsed = _diagnose_sql(request, loaded.sql)
        sql_diagnostic = SqlDiagnostic(
            source=request.sql_input.source if request.sql_input is not None else InputSource.INLINE,
            statement_type=parsed.statement_type,
            read_only=parsed.is_read_only,
            write=parsed.is_write,
            requires_explicit_transaction=parsed.requires_explicit_transaction,
            explain_analyze=parsed.is_explain_analyze,
            text_length=len(parsed.normalized_sql),
        )
    parameter_diagnostic = None
    if loaded.parameters is not None:
        parameter_diagnostic = ParameterDiagnostic(
            source=InputSource.PARAMS_FILE,
            kind=loaded.parameters.kind,
            count=loaded.parameters.count,
            path=loaded.parameters.source,
        )
    return CommandDiagnosticData(
        status=DiagnosticStatus.PARSED,
        command_group=request.group,
        action=request.action,
        sql=sql_diagnostic,
        parameters=parameter_diagnostic,
    )


def _policy_for_action(action: CommandAction) -> ExecutionPolicy | None:
    if action in {CommandAction.READ, CommandAction.BENCHMARK}:
        return ExecutionPolicy.READ_ONLY
    if action is CommandAction.WRITE:
        return ExecutionPolicy.WRITE
    if action is CommandAction.EXPLAIN:
        return ExecutionPolicy.EXPLAIN
    return None


def _validate_compare_inputs(request: CommandRequest, loaded: LoadedInputs) -> None:
    if loaded.compare_left_sql is None or loaded.compare_right_sql is None:
        raise _sql_failure(
            code=ErrorCode.INVALID_ARGUMENT,
            message="compare 必须提供左右两条 SQL",
            error_type=DiagnosticErrorType.MISSING_SQL,
            input_spec=None,
            argument="--left-sql|--left-sql-file|--right-sql|--right-sql-file",
        )
    _parse_and_validate_sql(
        loaded.compare_left_sql,
        policy=ExecutionPolicy.READ_ONLY,
        input_spec=request.compare_left_sql_input,
        argument="--left-sql|--left-sql-file",
    )
    _parse_and_validate_sql(
        loaded.compare_right_sql,
        policy=ExecutionPolicy.READ_ONLY,
        input_spec=request.compare_right_sql_input,
        argument="--right-sql|--right-sql-file",
    )


def _diagnose_sql(request: CommandRequest, sql: SqlInput) -> ParsedSql:
    """Classify one SQL input, delegating explicit ANALYZE wrapping to one helper."""

    if request.action is CommandAction.EXPLAIN and request.sql_explain_analyze:
        try:
            return build_explain_analyze(sql).parsed
        except ClientError as exc:
            raise _explain_analyze_failure(exc, request.sql_input) from exc
    return _parse_and_validate_sql(
        sql,
        policy=_policy_for_action(request.action),
        input_spec=request.sql_input,
        argument="--sql|--sql-file",
    )


def _explain_analyze_failure(error: ClientError, input_spec: SqlInputSpec | None) -> CliFailure:
    code: ErrorCode
    error_type: DiagnosticErrorType
    if error.code is ClientErrorCode.INVALID_SQL:
        code = ErrorCode.INVALID_SQL
        error_type = DiagnosticErrorType.SQL_PARSE
    elif error.code is ClientErrorCode.INVALID_ARGUMENT:
        code = ErrorCode.INVALID_ARGUMENT
        error_type = DiagnosticErrorType.ARGUMENT_SYNTAX
    elif error.code is ClientErrorCode.UNSUPPORTED_SQL:
        code = ErrorCode.UNSUPPORTED_SQL
        error_type = DiagnosticErrorType.POLICY_VIOLATION
    else:
        code = ErrorCode.INTERNAL_ERROR
        error_type = DiagnosticErrorType.EXECUTION
    source = input_spec.source if input_spec is not None else None
    message = error.message if error.hint is None else f"{error.message}; {error.hint}"
    return CliFailure(
        code=code,
        message=message,
        retryable=False,
        details=(ErrorDetail(error_type=error_type, argument="--analyze", source=source),),
        exit_code=ExitCode.INVALID_ARGUMENT,
    )


def _parse_and_validate_sql(
    sql: SqlInput,
    *,
    policy: ExecutionPolicy | None,
    input_spec: SqlInputSpec | None,
    argument: str,
) -> ParsedSql:
    try:
        parsed = MySqlSqlParser().parse(sql)
    except SqlParseError as exc:
        raise _sql_failure(
            code=ErrorCode.INVALID_SQL,
            message=exc.message,
            error_type=DiagnosticErrorType.SQL_PARSE,
            input_spec=input_spec,
            argument=argument,
        ) from exc
    except UnsupportedSqlError as exc:
        raise _sql_failure(
            code=ErrorCode.UNSUPPORTED_SQL,
            message=exc.message,
            error_type=DiagnosticErrorType.POLICY_VIOLATION,
            input_spec=input_spec,
            argument=argument,
        ) from exc
    if policy is None:
        return parsed
    try:
        validate_execution_policy(parsed, policy)
    except ExecutionPolicyError as exc:
        raise _sql_failure(
            code=ErrorCode.UNSUPPORTED_SQL,
            message=exc.message,
            error_type=DiagnosticErrorType.POLICY_VIOLATION,
            input_spec=input_spec,
            argument=argument,
        ) from exc
    return parsed


def _sql_failure(
    *,
    code: ErrorCode,
    message: str,
    error_type: DiagnosticErrorType,
    input_spec: SqlInputSpec | None,
    argument: str,
) -> CliFailure:
    source = input_spec.source if input_spec is not None else None
    return CliFailure(
        code=code,
        message=message,
        retryable=False,
        details=(ErrorDetail(error_type=error_type, argument=argument, source=source),),
        exit_code=ExitCode.INVALID_ARGUMENT,
    )


__all__ = ["CliRuntime", "CommandData", "diagnose", "execute_request", "request_requires_stdin"]
