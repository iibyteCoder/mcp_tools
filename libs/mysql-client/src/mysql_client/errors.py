"""Typed error hierarchy and stable error-report mapping."""

from __future__ import annotations

from typing import ClassVar

from mysql_client.enums import ErrorCode, ExitCode
from mysql_client.models import ErrorReport


class ClientError(Exception):
    """Base class for all expected MySQL Agent CLI failures."""

    code: ClassVar[ErrorCode] = ErrorCode.INTERNAL_ERROR

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint


class ConfigurationError(ClientError):
    """Connection or execution configuration is invalid."""

    code: ClassVar[ErrorCode] = ErrorCode.CONFIGURATION_FAILED


class InvalidArgumentError(ClientError):
    """A command argument is invalid."""

    code: ClassVar[ErrorCode] = ErrorCode.INVALID_ARGUMENT


class SqlParseError(ClientError):
    """SQL cannot be parsed safely."""

    code: ClassVar[ErrorCode] = ErrorCode.INVALID_SQL


class UnsupportedSqlError(ClientError):
    """The statement is valid but outside the supported command policy."""

    code: ClassVar[ErrorCode] = ErrorCode.UNSUPPORTED_SQL


class ConnectionError(ClientError):
    """The target cannot be reached or the session was lost."""

    code: ClassVar[ErrorCode] = ErrorCode.CONNECTION_FAILED


class AuthenticationError(ClientError):
    """The target rejected authentication or authorization."""

    code: ClassVar[ErrorCode] = ErrorCode.AUTHENTICATION_FAILED


class DatabaseNotFoundError(ClientError):
    """The requested database does not exist or is inaccessible."""

    code: ClassVar[ErrorCode] = ErrorCode.DATABASE_NOT_FOUND


class QueryExecutionError(ClientError):
    """The database rejected or failed to execute a query."""

    code: ClassVar[ErrorCode] = ErrorCode.QUERY_FAILED


class QueryTimeoutError(ClientError):
    """The query exceeded an execution policy deadline."""

    code: ClassVar[ErrorCode] = ErrorCode.TIMEOUT


class QueryCancelledError(ClientError):
    """The query was cooperatively cancelled."""

    code: ClassVar[ErrorCode] = ErrorCode.CANCELLED


class ComparisonError(ClientError):
    """Two query results could not be compared."""

    code: ClassVar[ErrorCode] = ErrorCode.COMPARISON_FAILED


class InternalError(ClientError):
    """Unexpected implementation failure."""

    code: ClassVar[ErrorCode] = ErrorCode.INTERNAL_ERROR


def exit_code_for_error(code: ErrorCode) -> ExitCode:
    """Map stable error codes to stable process exit codes."""

    if code is ErrorCode.INVALID_ARGUMENT or code is ErrorCode.INVALID_SQL or code is ErrorCode.UNSUPPORTED_SQL:
        return ExitCode.INVALID_ARGUMENT
    if code is ErrorCode.CONNECTION_FAILED or code is ErrorCode.DATABASE_NOT_FOUND:
        return ExitCode.CONNECTION_FAILED
    if code is ErrorCode.AUTHENTICATION_FAILED:
        return ExitCode.AUTHENTICATION_FAILED
    if code is ErrorCode.TIMEOUT:
        return ExitCode.TIMEOUT
    if code is ErrorCode.CANCELLED:
        return ExitCode.CANCELLED
    if code is ErrorCode.QUERY_FAILED or code is ErrorCode.COMPARISON_FAILED:
        return ExitCode.QUERY_FAILED
    return ExitCode.INTERNAL_ERROR


def error_report_from_exception(exc: BaseException) -> ErrorReport:
    """Convert expected and unexpected failures to a stable report."""

    if isinstance(exc, ClientError):
        code = exc.code
        message = exc.message
        hint = exc.hint
    elif isinstance(exc, (ValueError, TypeError)):
        code = ErrorCode.INVALID_ARGUMENT
        message = str(exc) or exc.__class__.__name__
        hint = None
    else:
        code = ErrorCode.INTERNAL_ERROR
        message = str(exc) or exc.__class__.__name__
        hint = None
    return ErrorReport(
        code=code,
        message=message,
        exit_code=exit_code_for_error(code),
        hint=hint,
        exception_type=exc.__class__.__name__,
    )
