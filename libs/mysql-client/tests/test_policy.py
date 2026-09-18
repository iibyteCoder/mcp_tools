from __future__ import annotations

import pytest

from mysql_client.domain.enums import ExecutionPolicy, PolicyViolationReason, SqlStatementType
from mysql_client.domain.errors import ExecutionPolicyError
from mysql_client.domain.values import SqlText
from mysql_client.sql.parser import MySqlSqlParser
from mysql_client.sql.policy import ExecutionPolicyValidator


@pytest.fixture
def parser() -> MySqlSqlParser:
    return MySqlSqlParser()


@pytest.fixture
def validator() -> ExecutionPolicyValidator:
    return ExecutionPolicyValidator()


@pytest.mark.parametrize(
    ("policy", "sql"),
    [
        (ExecutionPolicy.READ_ONLY, "SELECT 1"),
        (ExecutionPolicy.READ_ONLY, "SHOW TABLES"),
        (ExecutionPolicy.READ_ONLY, "DESCRIBE items"),
        (ExecutionPolicy.WRITE, "INSERT INTO items(id) VALUES (1)"),
        (ExecutionPolicy.WRITE, "UPDATE items SET id = 1"),
        (ExecutionPolicy.WRITE, "DELETE FROM items"),
        (ExecutionPolicy.WRITE, "CREATE TABLE items (id INT)"),
        (ExecutionPolicy.EXPLAIN, "EXPLAIN SELECT 1"),
        (ExecutionPolicy.EXPLAIN, "EXPLAIN ANALYZE SELECT 1"),
    ],
)
def test_policy_acceptance_matrix(
    parser: MySqlSqlParser,
    validator: ExecutionPolicyValidator,
    policy: ExecutionPolicy,
    sql: str,
) -> None:
    validator.validate(parser.parse(SqlText(sql)), policy)


@pytest.mark.parametrize(
    ("policy", "sql", "reason"),
    [
        (
            ExecutionPolicy.READ_ONLY,
            "INSERT INTO items(id) VALUES (1)",
            PolicyViolationReason.READ_ONLY_REQUIRES_READ_STATEMENT,
        ),
        (
            ExecutionPolicy.READ_ONLY,
            "EXPLAIN SELECT 1",
            PolicyViolationReason.READ_ONLY_REQUIRES_READ_STATEMENT,
        ),
        (
            ExecutionPolicy.WRITE,
            "SELECT 1",
            PolicyViolationReason.WRITE_REQUIRES_WRITE_STATEMENT,
        ),
        (
            ExecutionPolicy.WRITE,
            "EXPLAIN ANALYZE SELECT 1",
            PolicyViolationReason.WRITE_REQUIRES_WRITE_STATEMENT,
        ),
        (
            ExecutionPolicy.EXPLAIN,
            "SELECT 1",
            PolicyViolationReason.EXPLAIN_REQUIRES_EXPLAIN_STATEMENT,
        ),
        (
            ExecutionPolicy.EXPLAIN,
            "UPDATE items SET id = 1",
            PolicyViolationReason.EXPLAIN_REQUIRES_EXPLAIN_STATEMENT,
        ),
    ],
)
def test_policy_rejection_matrix(
    parser: MySqlSqlParser,
    validator: ExecutionPolicyValidator,
    policy: ExecutionPolicy,
    sql: str,
    reason: PolicyViolationReason,
) -> None:
    with pytest.raises(ExecutionPolicyError) as error:
        validator.validate(parser.parse(SqlText(sql)), policy)

    assert error.value.policy is policy
    assert error.value.reason is reason
    assert sql not in str(error.value)


@pytest.mark.parametrize(
    ("sql", "reason"),
    [
        ("SELECT * FROM items FOR UPDATE", "read_only_rejects_locking"),
        ("SELECT * FROM items LOCK IN SHARE MODE", "read_only_rejects_locking"),
        ("SELECT GET_LOCK('items', 1)", "read_only_rejects_side_effect"),
        ("SELECT RELEASE_LOCK('items')", "read_only_rejects_side_effect"),
        ("SELECT @item_count := COUNT(*) FROM items", "read_only_rejects_side_effect"),
    ],
)
def test_read_only_policy_rejects_locking_and_side_effects(
    parser: MySqlSqlParser,
    validator: ExecutionPolicyValidator,
    sql: str,
    reason: str,
) -> None:
    with pytest.raises(ExecutionPolicyError) as error:
        validator.validate(parser.parse(SqlText(sql)), ExecutionPolicy.READ_ONLY)

    assert error.value.reason.value == reason


def test_policy_does_not_rewrite_or_paginate_sql(
    parser: MySqlSqlParser,
    validator: ExecutionPolicyValidator,
) -> None:
    parsed = parser.parse(SqlText("SELECT id FROM items"))

    validator.validate(parsed, ExecutionPolicy.READ_ONLY)

    assert parsed.normalized_sql == "SELECT id FROM items"
    assert "LIMIT" not in parsed.normalized_sql.upper()
    assert "OFFSET" not in parsed.normalized_sql.upper()
    assert parsed.statement_type is SqlStatementType.SELECT
