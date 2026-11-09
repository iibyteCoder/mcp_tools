"""Execution-policy validation for locally parsed DM statements."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from dm_client.domain.enums import (
    ExecutionPolicy,
    PolicyViolationReason,
    SqlReadEffect,
    SqlStatementType,
)
from dm_client.domain.errors import ExecutionPolicyError, InvalidArgumentError, UnsupportedSqlError

if TYPE_CHECKING:
    from dm_client.domain.requests import ParsedSql

_READ_ONLY_STATEMENTS: Final[frozenset[SqlStatementType]] = frozenset(
    {
        SqlStatementType.SELECT,
        SqlStatementType.SHOW,
        SqlStatementType.DESCRIBE,
    }
)
_WRITE_STATEMENTS: Final[frozenset[SqlStatementType]] = frozenset(
    {
        SqlStatementType.INSERT,
        SqlStatementType.UPDATE,
        SqlStatementType.DELETE,
        SqlStatementType.MERGE,
        SqlStatementType.DDL,
        SqlStatementType.CALL,
        SqlStatementType.SET,
    }
)
_EXPLAIN_STATEMENTS: Final[frozenset[SqlStatementType]] = frozenset(
    {
        SqlStatementType.SELECT,
        SqlStatementType.INSERT,
        SqlStatementType.UPDATE,
        SqlStatementType.DELETE,
        SqlStatementType.MERGE,
        SqlStatementType.EXPLAIN,
    }
)


def validate_execution_policy(parsed_sql: ParsedSql, policy: ExecutionPolicy) -> None:
    """Raise when the parsed statement cannot run under ``policy``."""

    if policy is ExecutionPolicy.READ_ONLY:
        _validate_read_only(parsed_sql)
        return
    if policy is ExecutionPolicy.WRITE:
        _validate_write(parsed_sql)
        return
    if policy is ExecutionPolicy.EXPLAIN:
        _validate_explain(parsed_sql)
        return
    raise InvalidArgumentError("analyze execution policy does not apply to SQL statements")


def _validate_read_only(parsed_sql: ParsedSql) -> None:
    if parsed_sql.read_effect is SqlReadEffect.LOCKING:
        raise ExecutionPolicyError(
            ExecutionPolicy.READ_ONLY,
            PolicyViolationReason.READ_ONLY_REJECTS_LOCKING,
            hint="read-only policy rejects SELECT ... FOR UPDATE / FOR SHARE",
        )
    if parsed_sql.read_effect is SqlReadEffect.SESSION_STATE:
        raise ExecutionPolicyError(
            ExecutionPolicy.READ_ONLY,
            PolicyViolationReason.READ_ONLY_REJECTS_SESSION_STATE,
            hint="read-only policy rejects statements that change session state",
        )
    if parsed_sql.statement_type not in _READ_ONLY_STATEMENTS:
        raise ExecutionPolicyError(
            ExecutionPolicy.READ_ONLY,
            PolicyViolationReason.READ_ONLY_REQUIRES_READ_STATEMENT,
            hint="read-only policy accepts SELECT, SHOW and DESCRIBE only",
        )


def _validate_write(parsed_sql: ParsedSql) -> None:
    if parsed_sql.statement_type not in _WRITE_STATEMENTS:
        raise ExecutionPolicyError(
            ExecutionPolicy.WRITE,
            PolicyViolationReason.WRITE_REQUIRES_WRITE_STATEMENT,
            hint="write policy accepts INSERT, UPDATE, DELETE, MERGE, DDL, CALL and SET only",
        )


def _validate_explain(parsed_sql: ParsedSql) -> None:
    if parsed_sql.is_explain_analyze:
        raise UnsupportedSqlError(
            "EXPLAIN ANALYZE is not supported",
            hint="remove ANALYZE from the EXPLAIN statement",
        )
    if parsed_sql.statement_type not in _EXPLAIN_STATEMENTS:
        raise ExecutionPolicyError(
            ExecutionPolicy.EXPLAIN,
            PolicyViolationReason.EXPLAIN_REQUIRES_EXPLAINABLE_STATEMENT,
            hint="explain policy accepts SELECT, INSERT, UPDATE, DELETE, MERGE and EXPLAIN only",
        )


__all__ = ["validate_execution_policy"]
