"""Process entry point for the JSON-only MySQL CLI."""

from __future__ import annotations

import asyncio
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence
    from typing import TextIO

from mysql_cli import __version__
from mysql_cli.argument_parser import ParserExit, build_parser, parse_command_request
from mysql_cli.command_model import (
    CommandAction,
    CommandGroup,
    CommandRequest,
    DiagnosticErrorType,
    DiagnosticStatus,
    ErrorCode,
    ExitCode,
    InputSource,
    OutputMode,
)
from mysql_cli.errors import CliFailure, ErrorDetail
from mysql_cli.input_loader import LoadedInputs, load_inputs
from mysql_cli.inspection_service import InspectionService
from mysql_cli.json_codec import encode_json_document
from mysql_cli.output_model import (
    CommandDiagnosticData,
    DiagnosticMetadata,
    ErrorBody,
    ErrorEnvelope,
    InspectionCommandData,
    ParameterDiagnostic,
    ProfileCommandData,
    SqlCommandData,
    SqlDiagnostic,
    SuccessEnvelope,
)
from mysql_cli.profile_commands import execute_profile_command
from mysql_cli.profile_service import ProfileService, ProfileServiceError, ProfileServiceErrorCode
from mysql_cli.profile_store import JsonProfileStore, ProfileStoreError
from mysql_cli.secret_store import KeyringSecretStore
from mysql_cli.sql_service import SqlExecutionService
from mysql_client import (
    ClientError,
    ExecutionPolicy,
    ExecutionPolicyError,
    MySqlSqlParser,
    ParsedSql,
    SqlParseError,
    UnsupportedSqlError,
    error_report_from_exception,
    validate_execution_policy,
)
from mysql_client import (
    ErrorCode as ClientErrorCode,
)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return a stable process exit code."""

    arguments = tuple(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    request: CommandRequest | None = None
    try:
        request = parse_command_request(parser, arguments)
        if request.group is CommandGroup.HELP:
            parser.print_help()
            return int(ExitCode.SUCCESS)
        profile_service = ProfileService(
            JsonProfileStore(lock_timeout=JsonProfileStore.CLI_LOCK_TIMEOUT_SECONDS),
            KeyringSecretStore(),
        )
        if request.group is CommandGroup.PROFILE:
            profile_data: ProfileCommandData = asyncio.run(
                execute_profile_command(
                    request,
                    profile_service,
                )
            )
            envelope = SuccessEnvelope(
                ok=True,
                data=profile_data,
                meta=DiagnosticMetadata(command_group=request.group, action=request.action, input_source=None),
            )
            _write_json(envelope, sys.stdout)
            return int(ExitCode.SUCCESS)
        if request.group in {CommandGroup.SERVER, CommandGroup.SCHEMA}:
            inspection_data: InspectionCommandData = asyncio.run(
                InspectionService(profile_service).execute(request)
            )
            envelope = SuccessEnvelope(
                ok=True,
                data=inspection_data,
                meta=DiagnosticMetadata(command_group=request.group, action=request.action, input_source=None),
            )
            _write_json(envelope, sys.stdout)
            return int(ExitCode.SUCCESS)
        stdin_text = _read_stdin_if_needed(
            (request.sql_input is not None and request.sql_input.source is InputSource.STDIN)
            or (
                request.compare_left_sql_input is not None
                and request.compare_left_sql_input.source is InputSource.STDIN
            )
            or (
                request.compare_right_sql_input is not None
                and request.compare_right_sql_input.source is InputSource.STDIN
            )
        )
        loaded = load_inputs(request, stdin_text=stdin_text)
        if request.selected_profile is not None:
            sql_data: SqlCommandData = asyncio.run(SqlExecutionService(profile_service).execute(request, loaded))
            envelope = SuccessEnvelope(
                ok=True,
                data=sql_data,
                meta=DiagnosticMetadata(
                    command_group=request.group,
                    action=request.action,
                    input_source=request.sql_input.source if request.sql_input is not None else None,
                ),
            )
            _write_json(envelope, sys.stdout)
            return int(ExitCode.SUCCESS)
        diagnostic_data: CommandDiagnosticData = _diagnose(request, loaded)
        envelope = SuccessEnvelope(
            ok=True,
            data=diagnostic_data,
            meta=DiagnosticMetadata(
                command_group=request.group,
                action=request.action,
                input_source=request.sql_input.source if request.sql_input is not None else None,
            ),
        )
        _write_json(envelope, sys.stdout)
        return int(ExitCode.SUCCESS)
    except ParserExit as control:
        return control.status
    except CliFailure as cli_failure:
        _write_failure(cli_failure, sys.stdout, request=request)
        return int(cli_failure.exit_code)
    except ProfileStoreError as profile_error:
        failure = _profile_store_failure(profile_error)
        _write_failure(failure, sys.stdout, request=request)
        return int(failure.exit_code)
    except ProfileServiceError as profile_error:
        failure = _profile_service_failure(profile_error)
        _write_failure(failure, sys.stdout, request=request)
        return int(failure.exit_code)
    except ClientError as client_error:
        failure = _client_failure(client_error)
        _write_failure(failure, sys.stdout, request=request)
        return int(failure.exit_code)
    except KeyboardInterrupt:
        cancelled = CliFailure(
            code=ErrorCode.CANCELLED,
            message="操作已取消",
            retryable=False,
            details=(ErrorDetail(error_type=DiagnosticErrorType.CANCELLED),),
            exit_code=ExitCode.EXECUTION_ERROR,
        )
        _write_failure(cancelled, sys.stdout, request=request)
        return int(cancelled.exit_code)
    except Exception:
        internal_failure = CliFailure(
            code=ErrorCode.INTERNAL_ERROR,
            message="内部错误",
            retryable=False,
            details=(ErrorDetail(error_type=DiagnosticErrorType.ARGUMENT_SYNTAX),),
            exit_code=ExitCode.INTERNAL_ERROR,
        )
        _write_failure(internal_failure, sys.stdout, request=request)
        return int(internal_failure.exit_code)


def _diagnose(request: CommandRequest, loaded: LoadedInputs) -> CommandDiagnosticData:
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


def _read_stdin_if_needed(needed: bool) -> str | None:
    return sys.stdin.read() if needed else None


def _write_json(value: object, stream: TextIO) -> None:
    stream.write(encode_json_document(value))


def _write_failure(
    failure: CliFailure,
    stream: TextIO,
    *,
    request: CommandRequest | None,
) -> None:
    envelope = ErrorEnvelope(
        ok=False,
        error=ErrorBody(
            code=failure.code,
            message=failure.message,
            retryable=failure.retryable,
            details=failure.details,
            write_outcome=failure.write_outcome,
            differences=failure.differences,
        ),
        meta=DiagnosticMetadata(
            command_group=request.group if request is not None else None,
            action=request.action if request is not None else None,
            input_source=(request.sql_input.source if request is not None and request.sql_input is not None else None),
            output_mode=OutputMode.JSON,
        ),
    )
    _write_json(envelope, stream)


def _profile_store_failure(error: ProfileStoreError) -> CliFailure:
    mapping = {
        "profile_registry_corrupt": (ErrorCode.PROFILE_REGISTRY_CORRUPT, DiagnosticErrorType.PROFILE_REGISTRY_CORRUPT),
        "profile_registry_version_unsupported": (
            ErrorCode.PROFILE_REGISTRY_VERSION,
            DiagnosticErrorType.PROFILE_REGISTRY_VERSION,
        ),
        "profile_registry_locked": (ErrorCode.PROFILE_REGISTRY_LOCKED, DiagnosticErrorType.PROFILE_REGISTRY_LOCKED),
    }
    code, error_type = mapping.get(
        error.code.value,
        (ErrorCode.INPUT_ERROR, DiagnosticErrorType.FILE_READ_ERROR),
    )
    exit_code = ExitCode.PROFILE_ERROR if code is not ErrorCode.INPUT_ERROR else ExitCode.INPUT_ERROR
    return CliFailure(
        code=code,
        message=error.message,
        retryable=False,
        details=(ErrorDetail(error_type=error_type),),
        exit_code=exit_code,
    )


def _profile_service_failure(error: ProfileServiceError) -> CliFailure:
    mapping = {
        ProfileServiceErrorCode.NOT_FOUND: (ErrorCode.PROFILE_NOT_FOUND, DiagnosticErrorType.PROFILE_NOT_FOUND),
        ProfileServiceErrorCode.CONFLICT: (ErrorCode.PROFILE_CONFLICT, DiagnosticErrorType.PROFILE_CONFLICT),
        ProfileServiceErrorCode.INVALID: (ErrorCode.PROFILE_INVALID, DiagnosticErrorType.ARGUMENT_SYNTAX),
        ProfileServiceErrorCode.SECRET_MISSING: (ErrorCode.SECRET_STORE, DiagnosticErrorType.SECRET_STORE),
        ProfileServiceErrorCode.SECRET_STORE: (ErrorCode.SECRET_STORE, DiagnosticErrorType.SECRET_STORE),
        ProfileServiceErrorCode.VALIDATION_FAILED: (
            ErrorCode.PROFILE_VALIDATION_FAILED,
            DiagnosticErrorType.PROFILE_VALIDATION,
        ),
    }
    code, error_type = mapping[error.code]
    return CliFailure(
        code=code,
        message=error.message,
        retryable=False,
        details=(ErrorDetail(error_type=error_type),),
        exit_code=ExitCode.PROFILE_ERROR,
    )


def _client_failure(error: ClientError) -> CliFailure:
    report = error_report_from_exception(error)
    mapping = {
        ClientErrorCode.INVALID_ARGUMENT: (ErrorCode.INVALID_ARGUMENT, DiagnosticErrorType.ARGUMENT_SYNTAX),
        ClientErrorCode.CONFIGURATION_FAILED: (ErrorCode.CONFIGURATION_FAILED, DiagnosticErrorType.CONFIGURATION),
        ClientErrorCode.CONNECTION_FAILED: (ErrorCode.CONNECTION_FAILED, DiagnosticErrorType.CONNECTION),
        ClientErrorCode.AUTHENTICATION_FAILED: (
            ErrorCode.AUTHENTICATION_FAILED,
            DiagnosticErrorType.AUTHENTICATION,
        ),
        ClientErrorCode.DATABASE_NOT_FOUND: (ErrorCode.DATABASE_NOT_FOUND, DiagnosticErrorType.DATABASE_NOT_FOUND),
        ClientErrorCode.TIMEOUT: (ErrorCode.TIMEOUT, DiagnosticErrorType.TIMEOUT),
        ClientErrorCode.CANCELLED: (ErrorCode.CANCELLED, DiagnosticErrorType.CANCELLED),
        ClientErrorCode.QUERY_FAILED: (ErrorCode.EXECUTION_FAILED, DiagnosticErrorType.EXECUTION),
        ClientErrorCode.COMPARISON_FAILED: (ErrorCode.COMPARISON_FAILED, DiagnosticErrorType.COMPARISON),
        ClientErrorCode.UNSUPPORTED_SQL: (ErrorCode.UNSUPPORTED_SQL, DiagnosticErrorType.POLICY_VIOLATION),
        ClientErrorCode.INVALID_SQL: (ErrorCode.INVALID_SQL, DiagnosticErrorType.SQL_PARSE),
        ClientErrorCode.INTERNAL_ERROR: (ErrorCode.INTERNAL_ERROR, DiagnosticErrorType.EXECUTION),
    }
    code, error_type = mapping[error.code]
    exit_code = ExitCode.INVALID_ARGUMENT if code is ErrorCode.INVALID_ARGUMENT else ExitCode.EXECUTION_ERROR
    return CliFailure(
        code=code,
        message=error.message,
        retryable=False,
        details=(ErrorDetail(error_type=error_type),),
        exit_code=exit_code,
        write_outcome=report.write_outcome,
        differences=report.differences,
    )


__all__ = ["__version__", "main"]
