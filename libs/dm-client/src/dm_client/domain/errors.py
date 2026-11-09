"""Typed error hierarchy and stable error-report mapping for DM clients."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    from dm_client.domain.enums import ExecutionPolicy, PolicyViolationReason, SqlParseReason, WriteOutcome
    from dm_client.domain.results import ComparisonDifference


class ClientErrorCode(str, Enum):
    """Stable machine-readable error classifications owned by the client."""

    INVALID_ARGUMENT = "invalid_argument"
    INVALID_SQL = "invalid_sql"
    UNSUPPORTED_SQL = "unsupported_sql"
    CONFIGURATION_FAILED = "configuration_failed"
    CONNECTION_FAILED = "connection_failed"
    AUTHENTICATION_FAILED = "authentication_failed"
    PERMISSION_DENIED = "permission_denied"
    OBJECT_NOT_FOUND = "object_not_found"
    UNSUPPORTED_OBJECT = "unsupported_object"
    EXECUTION_FAILED = "execution_failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    COMPARISON_FAILED = "comparison_failed"
    INTERNAL_ERROR = "internal_error"


class ClientError(Exception):
    """Base class for all expected Dameng client failures."""

    code: ClassVar[ClientErrorCode] = ClientErrorCode.INTERNAL_ERROR

    def __init__(
        self,
        message: str,
        *,
        hint: str | None = None,
        write_outcome: WriteOutcome | None = None,
        differences: tuple[ComparisonDifference, ...] = (),
    ) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint
        self.write_outcome = write_outcome
        self.differences = differences


class ConfigurationError(ClientError):
    """Connection or execution configuration is invalid."""

    code: ClassVar[ClientErrorCode] = ClientErrorCode.CONFIGURATION_FAILED


class InvalidArgumentError(ClientError):
    """A request argument is invalid."""

    code: ClassVar[ClientErrorCode] = ClientErrorCode.INVALID_ARGUMENT


class SqlParseError(InvalidArgumentError):
    """SQL input cannot be reduced to exactly one safe statement."""

    code: ClassVar[ClientErrorCode] = ClientErrorCode.INVALID_SQL

    def __init__(
        self,
        message: str,
        *,
        reason: SqlParseReason,
        hint: str | None = None,
    ) -> None:
        self.reason = reason
        super().__init__(message, hint=hint)


class ConnectionError(ClientError):
    """The target cannot be reached or the session was lost."""

    code: ClassVar[ClientErrorCode] = ClientErrorCode.CONNECTION_FAILED


class AuthenticationError(ClientError):
    """The target rejected authentication or authorization."""

    code: ClassVar[ClientErrorCode] = ClientErrorCode.AUTHENTICATION_FAILED


class PermissionDeniedError(ClientError):
    """The current user lacks the privilege required by the command."""

    code: ClassVar[ClientErrorCode] = ClientErrorCode.PERMISSION_DENIED


class ObjectNotFoundError(ClientError):
    """The requested schema, table or database object does not exist."""

    code: ClassVar[ClientErrorCode] = ClientErrorCode.OBJECT_NOT_FOUND


class UnsupportedObjectError(ClientError):
    """The DM metadata package cannot produce DDL for the requested type."""

    code: ClassVar[ClientErrorCode] = ClientErrorCode.UNSUPPORTED_OBJECT


class QueryError(ClientError):
    """The database rejected or failed to execute a query."""

    code: ClassVar[ClientErrorCode] = ClientErrorCode.EXECUTION_FAILED


class WriteError(QueryError):
    """A write failed with an explicitly classified transaction outcome."""

    def __init__(self, message: str, *, outcome: WriteOutcome, hint: str | None = None) -> None:
        super().__init__(message, hint=hint, write_outcome=outcome)


class UnsupportedSqlError(ClientError):
    """The statement is valid but outside the supported command policy."""

    code: ClassVar[ClientErrorCode] = ClientErrorCode.UNSUPPORTED_SQL


class ExecutionPolicyError(UnsupportedSqlError):
    """A parsed statement does not match the caller's execution intent."""

    def __init__(
        self,
        policy: ExecutionPolicy,
        reason: PolicyViolationReason,
        *,
        hint: str | None = None,
    ) -> None:
        self.policy = policy
        self.reason = reason
        super().__init__("SQL statement does not satisfy the execution policy", hint=hint)


class QueryTimeoutError(ClientError):
    """The query exceeded an execution deadline."""

    code: ClassVar[ClientErrorCode] = ClientErrorCode.TIMEOUT


class QueryCancelledError(ClientError):
    """The query was cooperatively cancelled."""

    code: ClassVar[ClientErrorCode] = ClientErrorCode.CANCELLED


class ComparisonError(ClientError):
    """Two query results could not be compared."""

    code: ClassVar[ClientErrorCode] = ClientErrorCode.COMPARISON_FAILED

    def __init__(self, differences: tuple[ComparisonDifference, ...]) -> None:
        super().__init__(
            "comparison results are not equal",
            hint="check the result definitions and bound parameters of both SQL statements",
            differences=differences,
        )


class InternalError(ClientError):
    """Unexpected implementation failure."""

    code: ClassVar[ClientErrorCode] = ClientErrorCode.INTERNAL_ERROR


@dataclass(frozen=True, slots=True, kw_only=True)
class ErrorReport:
    """Stable structured error data without process or presentation policy."""

    code: ClientErrorCode
    message: str
    hint: str | None = None
    exception_type: str | None = None
    write_outcome: WriteOutcome | None = None
    differences: tuple[ComparisonDifference, ...] = ()


def error_report_from_exception(exc: BaseException) -> ErrorReport:
    """Convert expected and unexpected failures to a stable report."""

    if isinstance(exc, ClientError):
        return ErrorReport(
            code=exc.code,
            message=exc.message,
            hint=exc.hint,
            exception_type=exc.__class__.__name__,
            write_outcome=exc.write_outcome,
            differences=exc.differences,
        )
    code = ClientErrorCode.INVALID_ARGUMENT if isinstance(exc, (ValueError, TypeError)) else ClientErrorCode.INTERNAL_ERROR
    return ErrorReport(
        code=code,
        message=str(exc) or exc.__class__.__name__,
        exception_type=exc.__class__.__name__,
    )


__all__ = [
    "AuthenticationError",
    "ClientError",
    "ClientErrorCode",
    "ComparisonError",
    "ConfigurationError",
    "ConnectionError",
    "ErrorReport",
    "ExecutionPolicyError",
    "InternalError",
    "InvalidArgumentError",
    "ObjectNotFoundError",
    "PermissionDeniedError",
    "QueryCancelledError",
    "QueryError",
    "QueryTimeoutError",
    "SqlParseError",
    "UnsupportedObjectError",
    "UnsupportedSqlError",
    "WriteError",
    "error_report_from_exception",
]
