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


class ExecutionPolicy(str, Enum):
    """The only execution intents accepted by the client boundary."""

    READ_ONLY = "read_only"
    WRITE = "write"
    EXPLAIN = "explain"


class PolicyViolationReason(str, Enum):
    """Stable reasons for rejecting a parsed statement under a policy."""

    READ_ONLY_REQUIRES_READ_STATEMENT = "read_only_requires_read_statement"
    WRITE_REQUIRES_WRITE_STATEMENT = "write_requires_write_statement"
    EXPLAIN_REQUIRES_EXPLAIN_STATEMENT = "explain_requires_explain_statement"


class SqlParseReason(str, Enum):
    """Stable reasons for rejecting SQL before execution."""

    EMPTY = "empty"
    MULTIPLE_STATEMENTS = "multiple_statements"
    SYNTAX_ERROR = "syntax_error"


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


class TransactionAction(str, Enum):
    """The explicit transaction decision for one write request."""

    COMMIT = "commit"
    ROLLBACK = "rollback"


class DriverFailureKind(str, Enum):
    """Failure categories emitted by a driver adapter."""

    CONNECTION = "connection"
    PARAMETER = "parameter"
    AUTHENTICATION = "authentication"
    DATABASE_NOT_FOUND = "database_not_found"
    EXECUTION = "execution"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
