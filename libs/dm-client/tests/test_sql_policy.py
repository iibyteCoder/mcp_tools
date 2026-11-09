"""Unit tests for read/write/explain policy validation."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from dm_client.domain.enums import ExecutionPolicy, PolicyViolationReason
from dm_client.domain.errors import ExecutionPolicyError, InvalidArgumentError, UnsupportedSqlError
from dm_client.sql.parser import DmSqlParser
from dm_client.sql.policy import validate_execution_policy

if TYPE_CHECKING:
    from dm_client.domain.requests import ParsedSql

PARSER = DmSqlParser()


def parsed(sql: str) -> ParsedSql:
    return PARSER.parse(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1 FROM DUAL",
        "SHOW TABLES",
        "DESCRIBE some_table",
    ],
)
def test_read_only_accepts_read_statements(sql: str) -> None:
    validate_execution_policy(parsed(sql), ExecutionPolicy.READ_ONLY)


@pytest.mark.parametrize(
    ("sql", "reason"),
    [
        (
            "INSERT INTO t VALUES (1)",
            PolicyViolationReason.READ_ONLY_REQUIRES_READ_STATEMENT,
        ),
        (
            "EXPLAIN SELECT 1 FROM DUAL",
            PolicyViolationReason.READ_ONLY_REQUIRES_READ_STATEMENT,
        ),
        (
            "SELECT * FROM t FOR UPDATE",
            PolicyViolationReason.READ_ONLY_REJECTS_LOCKING,
        ),
        (
            "SET AUTOCOMMIT = 0",
            PolicyViolationReason.READ_ONLY_REJECTS_SESSION_STATE,
        ),
    ],
)
def test_read_only_rejects_write_locking_and_session_state(
    sql: str,
    reason: PolicyViolationReason,
) -> None:
    with pytest.raises(ExecutionPolicyError) as caught:
        validate_execution_policy(parsed(sql), ExecutionPolicy.READ_ONLY)

    assert caught.value.policy is ExecutionPolicy.READ_ONLY
    assert caught.value.reason is reason


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO t VALUES (1)",
        "UPDATE t SET x = 1",
        "DELETE FROM t",
        "MERGE INTO t USING s ON (t.id = s.id) WHEN MATCHED THEN UPDATE SET t.x = s.x",
        "CREATE TABLE t (id INT)",
        "CALL some_procedure(?)",
        "SET AUTOCOMMIT = 0",
    ],
)
def test_write_accepts_write_statements(sql: str) -> None:
    validate_execution_policy(parsed(sql), ExecutionPolicy.WRITE)


def test_write_rejects_read_statements() -> None:
    with pytest.raises(ExecutionPolicyError) as caught:
        validate_execution_policy(parsed("SELECT 1 FROM DUAL"), ExecutionPolicy.WRITE)

    assert caught.value.policy is ExecutionPolicy.WRITE
    assert caught.value.reason is PolicyViolationReason.WRITE_REQUIRES_WRITE_STATEMENT


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1 FROM DUAL",
        "INSERT INTO t VALUES (1)",
        "UPDATE t SET x = 1",
        "DELETE FROM t",
        "MERGE INTO t USING s ON (t.id = s.id) WHEN MATCHED THEN UPDATE SET t.x = s.x",
        "EXPLAIN SELECT 1 FROM DUAL",
    ],
)
def test_explain_accepts_explainable_statements(sql: str) -> None:
    validate_execution_policy(parsed(sql), ExecutionPolicy.EXPLAIN)


def test_explain_rejects_ddl() -> None:
    with pytest.raises(ExecutionPolicyError) as caught:
        validate_execution_policy(parsed("CREATE TABLE t (id INT)"), ExecutionPolicy.EXPLAIN)

    assert caught.value.reason is PolicyViolationReason.EXPLAIN_REQUIRES_EXPLAINABLE_STATEMENT


def test_explain_rejects_explain_analyze() -> None:
    with pytest.raises(UnsupportedSqlError):
        validate_execution_policy(
            parsed("EXPLAIN ANALYZE SELECT 1 FROM DUAL"),
            ExecutionPolicy.EXPLAIN,
        )


def test_analyze_policy_is_not_a_sql_policy() -> None:
    with pytest.raises(InvalidArgumentError):
        validate_execution_policy(parsed("SELECT 1 FROM DUAL"), ExecutionPolicy.ANALYZE)
