"""Compatibility imports for client errors."""

from mysql_client.domain.errors import (
    AuthenticationError,
    ClientError,
    ComparisonError,
    ConfigurationError,
    ConnectionError,
    DatabaseNotFoundError,
    ExecutionPolicyError,
    InternalError,
    InvalidArgumentError,
    QueryCancelledError,
    QueryExecutionError,
    QueryTimeoutError,
    SqlParseError,
    UnsupportedSqlError,
    WriteExecutionError,
    error_report_from_exception,
)

__all__ = [
    "AuthenticationError",
    "ClientError",
    "ComparisonError",
    "ConfigurationError",
    "ConnectionError",
    "DatabaseNotFoundError",
    "ExecutionPolicyError",
    "InternalError",
    "InvalidArgumentError",
    "QueryCancelledError",
    "QueryExecutionError",
    "QueryTimeoutError",
    "SqlParseError",
    "UnsupportedSqlError",
    "WriteExecutionError",
    "error_report_from_exception",
]
