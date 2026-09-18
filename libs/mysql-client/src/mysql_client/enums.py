"""Finite values owned by the MySQL client domain."""

from enum import Enum


class SqlStatementType(str, Enum):
    """Statement families understood by the execution policy."""

    SELECT = "select"
    INSERT = "insert"
    UPDATE = "update"
    DELETE = "delete"
    DDL = "ddl"
    SHOW = "show"
    DESCRIBE = "describe"
    EXPLAIN = "explain"
    UNKNOWN = "unknown"


class ErrorCode(str, Enum):
    """Stable machine-readable error classifications."""

    INVALID_ARGUMENT = "invalid_argument"
    INVALID_SQL = "invalid_sql"
    UNSUPPORTED_SQL = "unsupported_sql"
    CONFIGURATION_FAILED = "configuration_failed"
    CONNECTION_FAILED = "connection_failed"
    AUTHENTICATION_FAILED = "authentication_failed"
    DATABASE_NOT_FOUND = "database_not_found"
    QUERY_FAILED = "query_failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    COMPARISON_FAILED = "comparison_failed"
    INTERNAL_ERROR = "internal_error"


class ExplainFormat(str, Enum):
    """MySQL execution-plan formats."""

    TRADITIONAL = "traditional"
    JSON = "json"
    TREE = "tree"


class Capability(str, Enum):
    """Capabilities that a target or session may advertise."""

    READ = "read"
    WRITE = "write"
    EXPLAIN = "explain"
    BENCHMARK = "benchmark"
    COMPARE = "compare"
    TRANSACTIONS = "transactions"
    CANCELLATION = "cancellation"
    STREAMING = "streaming"


class InputSource(str, Enum):
    """Where SQL text came from."""

    INLINE = "inline"
    FILE = "file"
    STDIN = "stdin"


class CancellationReason(str, Enum):
    """Reasons supplied to an asynchronous cancellation controller."""

    USER_REQUEST = "user_request"
    SHUTDOWN = "shutdown"
    POLICY = "policy"
