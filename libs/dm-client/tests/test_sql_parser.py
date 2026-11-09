"""Unit tests for the local DM SQL parser and explain-prefix helper."""

from __future__ import annotations

import pytest

from dm_client.domain.enums import SqlParseReason, SqlReadEffect, SqlStatementType
from dm_client.domain.errors import SqlParseError
from dm_client.domain.requests import SqlInput
from dm_client.sql.parser import DmSqlParser, strip_explain_prefix


@pytest.mark.parametrize(
    "text",
    ["", "   ", ";", "; /* only a comment */", "-- only a comment"],
)
def test_empty_input_is_rejected(text: str) -> None:
    with pytest.raises(SqlParseError) as caught:
        DmSqlParser().parse(text)

    assert caught.value.reason is SqlParseReason.EMPTY


@pytest.mark.parametrize(
    "text",
    [
        "SELECT 1 FROM DUAL; SELECT 2 FROM DUAL",
        "SELECT 1;;",
        "SELECT 1; SELECT 2;",
    ],
)
def test_multiple_statements_are_rejected(text: str) -> None:
    with pytest.raises(SqlParseError) as caught:
        DmSqlParser().parse(text)

    assert caught.value.reason is SqlParseReason.MULTIPLE_STATEMENTS


def test_one_trailing_semicolon_is_allowed_and_normalized() -> None:
    parsed = DmSqlParser().parse("  SELECT 1 AS N FROM DUAL;  ")

    assert parsed.statement_type is SqlStatementType.SELECT
    assert parsed.normalized_sql == "SELECT 1 AS N FROM DUAL"


def test_interior_text_is_not_rewritten() -> None:
    parsed = DmSqlParser().parse("  SELECT  1 ;  ")

    assert parsed.normalized_sql == "SELECT  1"


@pytest.mark.parametrize(
    "text",
    [
        "SELECT 'a;b' AS value FROM DUAL",
        'SELECT "a;b" FROM DUAL',
        "SELECT 1 /* ; */ FROM DUAL",
        "SELECT 1 -- ;\nFROM DUAL",
        "-- a; b\nSELECT 1 FROM DUAL",
    ],
)
def test_semicolons_inside_literals_and_comments_are_ignored(text: str) -> None:
    parsed = DmSqlParser().parse(text)

    assert parsed.statement_type is SqlStatementType.SELECT
    assert parsed.is_read_only is True


@pytest.mark.parametrize(
    "text",
    ["SELECT 'abc", 'SELECT "abc', "SELECT 'it''s"],
)
def test_unterminated_quotes_are_rejected(text: str) -> None:
    with pytest.raises(SqlParseError) as caught:
        DmSqlParser().parse(text)

    assert caught.value.reason is SqlParseReason.UNTERMINATED_QUOTE


def test_unterminated_block_comment_is_rejected() -> None:
    with pytest.raises(SqlParseError) as caught:
        DmSqlParser().parse("SELECT 1 /* never closed")

    assert caught.value.reason is SqlParseReason.UNTERMINATED_COMMENT


def test_doubled_quotes_are_escapes() -> None:
    parsed = DmSqlParser().parse("SELECT 'it''s; fine' AS value FROM DUAL")

    assert parsed.statement_type is SqlStatementType.SELECT


@pytest.mark.parametrize(
    ("text", "statement_type"),
    [
        ("SELECT 1 FROM DUAL", SqlStatementType.SELECT),
        ("SHOW TABLES", SqlStatementType.SHOW),
        ("DESCRIBE some_table", SqlStatementType.DESCRIBE),
        ("DESC some_table", SqlStatementType.DESCRIBE),
        ("INSERT INTO t VALUES (1)", SqlStatementType.INSERT),
        ("UPDATE t SET x = 1", SqlStatementType.UPDATE),
        ("DELETE FROM t", SqlStatementType.DELETE),
        (
            "MERGE INTO t USING s ON (t.id = s.id) WHEN MATCHED THEN UPDATE SET t.x = s.x",
            SqlStatementType.MERGE,
        ),
        ("CALL some_procedure(?)", SqlStatementType.CALL),
        ("SET AUTOCOMMIT = 0", SqlStatementType.SET),
        ("CREATE TABLE t (id INT)", SqlStatementType.DDL),
        ("ALTER TABLE t ADD COLUMN name VARCHAR(20)", SqlStatementType.DDL),
        ("DROP TABLE t", SqlStatementType.DDL),
        ("TRUNCATE TABLE t", SqlStatementType.DDL),
        ("RENAME TABLE a TO b", SqlStatementType.DDL),
        ("COMMENT ON TABLE t IS 'x'", SqlStatementType.DDL),
        ("GRANT SELECT ON t TO u", SqlStatementType.DDL),
        ("REVOKE SELECT ON t FROM u", SqlStatementType.DDL),
        ("BEGIN", SqlStatementType.OTHER),
    ],
)
def test_first_keyword_classification(text: str, statement_type: SqlStatementType) -> None:
    parsed = DmSqlParser().parse(text)

    assert parsed.statement_type is statement_type
    assert parsed.is_read_only is (statement_type in {
        SqlStatementType.SELECT,
        SqlStatementType.SHOW,
        SqlStatementType.DESCRIBE,
        SqlStatementType.EXPLAIN,
    })
    assert parsed.is_write is (statement_type in {
        SqlStatementType.INSERT,
        SqlStatementType.UPDATE,
        SqlStatementType.DELETE,
        SqlStatementType.MERGE,
        SqlStatementType.DDL,
        SqlStatementType.CALL,
        SqlStatementType.SET,
    })


@pytest.mark.parametrize(
    ("text", "statement_type"),
    [
        (
            "WITH cte AS (SELECT 1 AS n FROM DUAL) SELECT n FROM cte",
            SqlStatementType.SELECT,
        ),
        (
            "WITH cte AS (SELECT 1 FROM DUAL) INSERT INTO t SELECT * FROM cte",
            SqlStatementType.INSERT,
        ),
        (
            "WITH cte AS (SELECT 1 FROM DUAL) UPDATE t SET x = 1",
            SqlStatementType.UPDATE,
        ),
        (
            "WITH cte AS (SELECT 1 FROM DUAL) DELETE FROM t",
            SqlStatementType.DELETE,
        ),
        (
            "WITH cte AS (SELECT 1 FROM DUAL) MERGE INTO t USING cte ON (1 = 1) "
            "WHEN MATCHED THEN UPDATE SET x = 1",
            SqlStatementType.MERGE,
        ),
    ],
)
def test_cte_with_statement_classifies_the_main_statement(
    text: str,
    statement_type: SqlStatementType,
) -> None:
    parsed = DmSqlParser().parse(text)

    assert parsed.statement_type is statement_type


def test_cte_select_for_update_stays_a_locking_select() -> None:
    parsed = DmSqlParser().parse(
        "WITH cte AS (SELECT id FROM t) SELECT id FROM cte FOR UPDATE"
    )

    assert parsed.statement_type is SqlStatementType.SELECT
    assert parsed.read_effect is SqlReadEffect.LOCKING


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("SELECT * FROM t FOR UPDATE", SqlReadEffect.LOCKING),
        ("SELECT * FROM t FOR SHARE", SqlReadEffect.LOCKING),
        ("SELECT * FROM t", SqlReadEffect.NONE),
        ("SET AUTOCOMMIT = 0", SqlReadEffect.SESSION_STATE),
        ("UPDATE t SET x = 1", SqlReadEffect.NONE),
    ],
)
def test_read_effect_classification(text: str, expected: SqlReadEffect) -> None:
    parsed = DmSqlParser().parse(text)

    assert parsed.read_effect is expected


def test_explain_and_explain_analyze_are_distinguished() -> None:
    explain = DmSqlParser().parse("EXPLAIN SELECT 1 FROM DUAL")
    analyze = DmSqlParser().parse("EXPLAIN ANALYZE SELECT 1 FROM DUAL")

    assert explain.statement_type is SqlStatementType.EXPLAIN
    assert explain.is_read_only is True
    assert explain.is_explain_analyze is False
    assert analyze.is_explain_analyze is True


def test_write_requires_explicit_transaction() -> None:
    write = DmSqlParser().parse("INSERT INTO t VALUES (1)")
    read = DmSqlParser().parse("SELECT 1 FROM DUAL")

    assert write.requires_explicit_transaction is True
    assert read.requires_explicit_transaction is False


def test_sql_input_is_accepted() -> None:
    parsed = DmSqlParser().parse(SqlInput.inline("SELECT 1 FROM DUAL;"))

    assert parsed.statement_type is SqlStatementType.SELECT


def test_strip_explain_prefix_variants() -> None:
    assert strip_explain_prefix("  EXPLAIN SELECT 1 FROM DUAL  ") == "SELECT 1 FROM DUAL"
    assert strip_explain_prefix("EXPLAIN ANALYZE DELETE FROM t") == "DELETE FROM t"
    assert strip_explain_prefix("SELECT 1 FROM DUAL") == "SELECT 1 FROM DUAL"
    assert strip_explain_prefix("EXPLAIN") == ""
    assert strip_explain_prefix("EXPLAIN /* c */ ANALYZE SELECT 1 FROM DUAL") == "SELECT 1 FROM DUAL"
    assert strip_explain_prefix("EXPLAINED SELECT 1") == "EXPLAINED SELECT 1"


def test_sql_parse_error_carries_invalid_sql_code_and_reason() -> None:
    with pytest.raises(SqlParseError) as caught:
        DmSqlParser().parse("")

    assert caught.value.code.value == "invalid_sql"
    assert caught.value.reason is SqlParseReason.EMPTY
