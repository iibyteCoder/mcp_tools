"""Explicit execution-policy validation for parsed MySQL statements."""

from __future__ import annotations

from typing import TYPE_CHECKING

from mysql_client.domain.enums import (
    ExecutionPolicy,
    PolicyViolationReason,
    SqlStatementType,
)
from mysql_client.domain.errors import ExecutionPolicyError

if TYPE_CHECKING:
    from mysql_client.domain.requests import ParsedSql

_READ_STATEMENTS = frozenset(
    {
        SqlStatementType.SELECT,
        SqlStatementType.SHOW,
        SqlStatementType.DESCRIBE,
    }
)
_WRITE_STATEMENTS = frozenset(
    {
        SqlStatementType.INSERT,
        SqlStatementType.UPDATE,
        SqlStatementType.DELETE,
        SqlStatementType.DDL,
    }
)
_EXPLAIN_STATEMENTS = frozenset({SqlStatementType.EXPLAIN})


class ExecutionPolicyValidator:
    """Validate command intent without rewriting or executing SQL."""

    def validate(self, parsed_sql: ParsedSql, policy: ExecutionPolicy) -> None:
        """Raise when ``parsed_sql`` cannot be executed under ``policy``."""

        allowed_statements = self._allowed_statements(policy)
        if parsed_sql.statement_type in allowed_statements:
            return
        raise ExecutionPolicyError(
            policy,
            self._violation_reason(policy),
            hint=self._hint(policy),
        )

    @staticmethod
    def _allowed_statements(policy: ExecutionPolicy) -> frozenset[SqlStatementType]:
        if policy is ExecutionPolicy.READ_ONLY:
            return _READ_STATEMENTS
        if policy is ExecutionPolicy.WRITE:
            return _WRITE_STATEMENTS
        return _EXPLAIN_STATEMENTS

    @staticmethod
    def _violation_reason(policy: ExecutionPolicy) -> PolicyViolationReason:
        if policy is ExecutionPolicy.READ_ONLY:
            return PolicyViolationReason.READ_ONLY_REQUIRES_READ_STATEMENT
        if policy is ExecutionPolicy.WRITE:
            return PolicyViolationReason.WRITE_REQUIRES_WRITE_STATEMENT
        return PolicyViolationReason.EXPLAIN_REQUIRES_EXPLAIN_STATEMENT

    @staticmethod
    def _hint(policy: ExecutionPolicy) -> str:
        if policy is ExecutionPolicy.READ_ONLY:
            return "只读策略仅允许 SELECT、SHOW 和 DESCRIBE"
        if policy is ExecutionPolicy.WRITE:
            return "写入策略仅允许 INSERT、UPDATE、DELETE 和 DDL"
        return "执行计划策略仅允许 EXPLAIN 或 EXPLAIN ANALYZE"


def validate_execution_policy(
    parsed_sql: ParsedSql,
    policy: ExecutionPolicy,
) -> None:
    """Validate one parsed statement against one explicit execution policy."""

    ExecutionPolicyValidator().validate(parsed_sql, policy)
