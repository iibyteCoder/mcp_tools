"""Framework-neutral command orchestration for the MySQL CLI boundary."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Protocol

from mysql_cli.command_model import (
    CommandAction,
    CommandGroup,
    CommandRequest,
    DiagnosticErrorType,
    DiagnosticStatus,
    ErrorCode,
    ExitCode,
    InputSource,
)
from mysql_cli.errors import CliFailure, ErrorDetail
from mysql_cli.input_loader import LoadedInputs, load_inputs
from mysql_cli.inspection_service import InspectionService
from mysql_cli.output_model import (
    CommandDiagnosticData,
    InspectionCommandData,
    ParameterDiagnostic,
    ProfileCommandData,
    SqlCommandData,
    SqlDiagnostic,
)
from mysql_cli.profile_commands import execute_profile_command
from mysql_cli.profile_service import ProfileService
from mysql_cli.profile_store import JsonProfileStore
from mysql_cli.secret_store import KeyringSecretStore
from mysql_cli.sql_service import SqlExecutionService
from mysql_client import (
    ExecutionPolicy,
    ExecutionPolicyError,
    MySqlSqlParser,
    ParsedSql,
    SqlParseError,
    UnsupportedSqlError,
    validate_execution_policy,
)

if TYPE_CHECKING:
    from mysql_cli.profile_models import ProfileName


CommandData = CommandDiagnosticData | ProfileCommandData | InspectionCommandData | SqlCommandData


class InspectionExecutor(Protocol):
    """Typed inspection service dependency used by command orchestration."""

    async def execute(self, request: CommandRequest) -> InspectionCommandData: ...


class SqlExecutor(Protocol):
    """Typed SQL service dependency used by command orchestration."""

    async def execute(self, request: CommandRequest, inputs: LoadedInputs) -> SqlCommandData: ...


@dataclass(slots=True)
class CliRuntime:
    """Mutable invocation state kept outside the Click command callbacks."""

    profile_service: ProfileService
    inspection_service: InspectionExecutor | None = None
    sql_service: SqlExecutor | None = None
    selected_profile: ProfileName | None = None
    request: CommandRequest | None = None

    @classmethod
    def create_default(cls) -> CliRuntime:
        """Build production services without contacting a database."""

        profiles = ProfileService(
            JsonProfileStore(lock_timeout=JsonProfileStore.CLI_LOCK_TIMEOUT_SECONDS),
            KeyringSecretStore(),
        )
        return cls(profile_service=profiles)


def request_requires_stdin(request: CommandRequest) -> bool:
    """Return whether the command needs one SQL document from standard input."""

    return request.sql_input is not None and request.sql_input.source is InputSource.STDIN


def execute_request(runtime: CliRuntime, request: CommandRequest, *, stdin_text: str | None) -> CommandData:
    """Execute one validated request or return its parse-only diagnostic result."""

    if request.selected_profile is None and runtime.selected_profile is not None:
        request = replace(request, selected_profile=runtime.selected_profile)
    runtime.request = request

    if request.group is CommandGroup.PROFILE:
        return asyncio.run(execute_profile_command(request, runtime.profile_service))
    if request.group in {CommandGroup.SERVER, CommandGroup.SCHEMA}:
        inspection_service = runtime.inspection_service or InspectionService(runtime.profile_service)
        runtime.inspection_service = inspection_service
        return asyncio.run(inspection_service.execute(request))
    if request.group is not CommandGroup.SQL:
        raise ValueError("unsupported command group")

    loaded = load_inputs(request, stdin_text=stdin_text)
    if request.selected_profile is not None:
        sql_service = runtime.sql_service or SqlExecutionService(runtime.profile_service)
        runtime.sql_service = sql_service
        return asyncio.run(sql_service.execute(request, loaded))
    return diagnose(request, loaded)


def diagnose(request: CommandRequest, loaded: LoadedInputs) -> CommandDiagnosticData:
    """Parse and classify SQL without selecting or contacting a database."""

    sql_diagnostic: SqlDiagnostic | None = None
    if loaded.sql is not None:
        try:
            parsed = MySqlSqlParser().parse(loaded.sql)
        except SqlParseError as exc:
            raise _sql_failure(
                code=ErrorCode.INVALID_SQL,
                message=exc.message,
                error_type=DiagnosticErrorType.SQL_PARSE,
                request=request,
            ) from exc
        except UnsupportedSqlError as exc:
            raise _sql_failure(
                code=ErrorCode.UNSUPPORTED_SQL,
                message=exc.message,
                error_type=DiagnosticErrorType.POLICY_VIOLATION,
                request=request,
            ) from exc
        _validate_policy_if_required(request.action, parsed, request=request)
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


def _validate_policy_if_required(action: CommandAction, parsed: ParsedSql, *, request: CommandRequest) -> None:
    if action is CommandAction.READ:
        policy = ExecutionPolicy.READ_ONLY
    elif action is CommandAction.WRITE:
        policy = ExecutionPolicy.WRITE
    elif action is CommandAction.EXPLAIN:
        policy = ExecutionPolicy.EXPLAIN
    else:
        return
    try:
        validate_execution_policy(parsed, policy)
    except ExecutionPolicyError as exc:
        raise _sql_failure(
            code=ErrorCode.UNSUPPORTED_SQL,
            message=exc.message,
            error_type=DiagnosticErrorType.POLICY_VIOLATION,
            request=request,
        ) from exc


def _sql_failure(
    *,
    code: ErrorCode,
    message: str,
    error_type: DiagnosticErrorType,
    request: CommandRequest | None,
) -> CliFailure:
    source = request.sql_input.source if request is not None and request.sql_input is not None else None
    return CliFailure(
        code=code,
        message=message,
        retryable=False,
        details=(ErrorDetail(error_type=error_type, argument="--sql|--sql-file", source=source),),
        exit_code=ExitCode.INVALID_ARGUMENT,
    )


__all__ = ["CliRuntime", "CommandData", "diagnose", "execute_request", "request_requires_stdin"]
