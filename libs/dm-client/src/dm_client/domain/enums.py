"""Finite control values owned by the Dameng client domain."""

from __future__ import annotations

from enum import Enum
from typing import Final


class SqlStatementType(str, Enum):
    """Statement families understood by the execution policy."""

    SELECT = "select"
    INSERT = "insert"
    UPDATE = "update"
    DELETE = "delete"
    MERGE = "merge"
    DDL = "ddl"
    SHOW = "show"
    DESCRIBE = "describe"
    EXPLAIN = "explain"
    CALL = "call"
    SET = "set"
    OTHER = "other"


class ExecutionPolicy(str, Enum):
    """The execution intents accepted by the client boundary."""

    READ_ONLY = "read_only"
    WRITE = "write"
    EXPLAIN = "explain"
    ANALYZE = "analyze"


class PolicyViolationReason(str, Enum):
    """Stable reasons for rejecting a parsed statement under a policy."""

    READ_ONLY_REQUIRES_READ_STATEMENT = "read_only_requires_read_statement"
    WRITE_REQUIRES_WRITE_STATEMENT = "write_requires_write_statement"
    EXPLAIN_REQUIRES_EXPLAINABLE_STATEMENT = "explain_requires_explainable_statement"
    ANALYZE_REQUIRES_TABLE = "analyze_requires_table"
    READ_ONLY_REJECTS_LOCKING = "read_only_rejects_locking"
    READ_ONLY_REJECTS_SESSION_STATE = "read_only_rejects_session_state"


class SqlReadEffect(str, Enum):
    """Observable effects that make a syntactic read unsafe for read-only policy."""

    NONE = "none"
    LOCKING = "locking"
    SESSION_STATE = "session_state"


class SqlParseReason(str, Enum):
    """Stable reasons for rejecting SQL before any driver call."""

    EMPTY = "empty"
    MULTIPLE_STATEMENTS = "multiple_statements"
    UNTERMINATED_QUOTE = "unterminated_quote"
    UNTERMINATED_COMMENT = "unterminated_comment"
    MALFORMED = "malformed"


class TransactionAction(str, Enum):
    """The explicit transaction decision for one write request."""

    COMMIT = "commit"
    ROLLBACK = "rollback"


class WriteOutcome(str, Enum):
    """Known or unknown transaction state after a write attempt."""

    COMMITTED = "committed"
    ROLLED_BACK = "rolled_back"
    DETERMINED_FAILURE = "determined_failure"
    UNKNOWN = "unknown"


class ObjectType(str, Enum):
    """Object types addressable by schema catalog commands."""

    TABLE = "table"
    VIEW = "view"
    INDEX = "index"
    SEQUENCE = "sequence"
    SYNONYM = "synonym"
    PROCEDURE = "procedure"
    FUNCTION = "function"
    PACKAGE = "package"
    TRIGGER = "trigger"


class ConstraintType(str, Enum):
    """Constraint categories reported by the DM catalog."""

    PRIMARY_KEY = "primary_key"
    UNIQUE = "unique"
    FOREIGN_KEY = "foreign_key"
    CHECK = "check"
    UNKNOWN = "unknown"


class ParameterKey(str, Enum):
    """DM server parameters exposed as typed capability facts."""

    COMPATIBLE_MODE = "COMPATIBLE_MODE"
    CASE_SENSITIVE = "CASE_SENSITIVE"
    JSON_MODE = "JSON_MODE"
    USE_JSON_DATATYPE = "USE_JSON_DATATYPE"
    BLANK_PAD_MODE = "BLANK_PAD_MODE"
    LENGTH_IN_CHAR = "LENGTH_IN_CHAR"
    PAGE_SIZE = "PAGE_SIZE"
    EXTENT_SIZE = "EXTENT_SIZE"
    BUFFER = "BUFFER"
    MAX_SESSIONS = "MAX_SESSIONS"
    PORT_NUM = "PORT_NUM"
    INSTANCE_NAME = "INSTANCE_NAME"


class SystemSchema(str, Enum):
    """DM-supplied schemas hidden by default from schema listings."""

    SYS = "SYS"
    SYSDBA = "SYSDBA"
    SYSAUDITOR = "SYSAUDITOR"
    SYSSSO = "SYSSSO"


class SensitiveParameterMarker(str, Enum):
    """Substrings that make a server parameter value sensitive."""

    PWD = "PWD"
    PASSWORD = "PASSWORD"
    PASSWD = "PASSWD"
    SECRET = "SECRET"
    PRIVATE_KEY = "PRIVATE_KEY"


class PlanParseStatus(str, Enum):
    """Best-effort parse state of a DM text execution plan."""

    PARSED = "parsed"
    PARTIAL = "partial"
    FAILED = "failed"


class InspectionKind(str, Enum):
    """Read-only server and schema inspection operations."""

    SERVER_INSPECT = "server_inspect"
    SERVER_CAPABILITIES = "server_capabilities"
    SERVER_PARAMETERS = "server_parameters"
    SCHEMA_DATABASES = "schema_databases"
    SCHEMA_TABLES = "schema_tables"
    SCHEMA_DESCRIBE = "schema_describe"
    SCHEMA_INDEXES = "schema_indexes"
    SCHEMA_STATS = "schema_stats"
    SCHEMA_CONSTRAINTS = "schema_constraints"
    SCHEMA_OBJECTS = "schema_objects"
    SCHEMA_DDL = "schema_ddl"


class ComparisonDifferenceKind(str, Enum):
    """Stable categories for differences between two compared result sets."""

    COLUMN_DEFINITION = "column_definition"
    ROW_COUNT = "row_count"
    ROW_VALUE = "row_value"
    KEY_COLUMN = "key_column"
    DUPLICATE_KEY = "duplicate_key"


class ComparisonLocation(str, Enum):
    """Stable locations used in comparison difference reports."""

    COLUMNS = "columns"
    ROW_COUNT = "rows.count"
    ROW = "row"
    LEFT_MISSING_KEY = "left.missing_key"
    RIGHT_MISSING_KEY = "right.missing_key"
    LEFT_DUPLICATE_KEY = "left.duplicate_key"
    RIGHT_DUPLICATE_KEY = "right.duplicate_key"


class ComparisonSide(str, Enum):
    """Side labels used while comparing two result sets."""

    LEFT = "left"
    RIGHT = "right"


SYSTEM_SCHEMAS: Final[tuple[SystemSchema, ...]] = tuple(SystemSchema)
SENSITIVE_PARAMETER_MARKERS: Final[tuple[SensitiveParameterMarker, ...]] = tuple(SensitiveParameterMarker)
KEY_SERVER_PARAMETERS: Final[tuple[ParameterKey, ...]] = (
    ParameterKey.COMPATIBLE_MODE,
    ParameterKey.CASE_SENSITIVE,
    ParameterKey.JSON_MODE,
    ParameterKey.USE_JSON_DATATYPE,
    ParameterKey.BLANK_PAD_MODE,
    ParameterKey.LENGTH_IN_CHAR,
    ParameterKey.PAGE_SIZE,
    ParameterKey.EXTENT_SIZE,
    ParameterKey.BUFFER,
    ParameterKey.MAX_SESSIONS,
    ParameterKey.PORT_NUM,
    ParameterKey.INSTANCE_NAME,
)


__all__ = [
    "KEY_SERVER_PARAMETERS",
    "SENSITIVE_PARAMETER_MARKERS",
    "SYSTEM_SCHEMAS",
    "ComparisonDifferenceKind",
    "ComparisonLocation",
    "ComparisonSide",
    "ConstraintType",
    "ExecutionPolicy",
    "InspectionKind",
    "ObjectType",
    "ParameterKey",
    "PlanParseStatus",
    "PolicyViolationReason",
    "SensitiveParameterMarker",
    "SqlParseReason",
    "SqlReadEffect",
    "SqlStatementType",
    "SystemSchema",
    "TransactionAction",
    "WriteOutcome",
]
