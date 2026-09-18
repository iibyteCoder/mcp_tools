"""Process entry point for the JSON-only agent-first MySQL CLI."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence
    from typing import TextIO

from mysql_client import (
    ExecutionPolicy,
    ExecutionPolicyError,
    MySqlSqlParser,
    ParsedSql,
    SqlParseError,
    UnsupportedSqlError,
    validate_execution_policy,
)
from mysql_command import __version__
from mysql_command.argument_parser import ParserExit, build_parser, parse_command_request
from mysql_command.command_model import (
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
from mysql_command.errors import CliFailure, ErrorDetail
from mysql_command.input_loader import LoadedInputs, load_inputs
from mysql_command.json_codec import encode_json_document
from mysql_command.output_model import (
    CommandDiagnosticData,
    DiagnosticMetadata,
    ErrorBody,
    ErrorEnvelope,
    ParameterDiagnostic,
    SqlDiagnostic,
    SuccessEnvelope,
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
        stdin_text = _read_stdin_if_needed(request.sql_input is not None and request.sql_input.source is InputSource.STDIN)
        loaded = load_inputs(request, stdin_text=stdin_text)
        data = _diagnose(request, loaded)
        envelope = SuccessEnvelope(
            ok=True,
            data=data,
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
        ),
        meta=DiagnosticMetadata(
            command_group=request.group if request is not None else None,
            action=request.action if request is not None else None,
            input_source=(
                request.sql_input.source
                if request is not None and request.sql_input is not None
                else None
            ),
            output_mode=OutputMode.JSON,
        ),
    )
    _write_json(envelope, stream)


__all__ = ["__version__", "main"]
