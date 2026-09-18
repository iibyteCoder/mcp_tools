from __future__ import annotations

import pytest

from mysql_client.enums import SqlParseReason, SqlStatementType
from mysql_client.errors import SqlParseError, UnsupportedSqlError
from mysql_client.parser import MySqlSqlParser
from mysql_client.request_models import SqlInput
from mysql_client.value_models import SqlText


@pytest.fixture
def parser() -> MySqlSqlParser:
    return MySqlSqlParser()


@pytest.mark.parametrize("sql", [SqlText(""), SqlText(" \n\t "), SqlText(";")])
def test_parser_rejects_empty_sql(parser: MySqlSqlParser, sql: SqlText) -> None:
    with pytest.raises(SqlParseError) as error:
        parser.parse(sql)

    assert error.value.reason is SqlParseReason.EMPTY


def test_parser_accepts_sql_input_and_preserves_original_text(
    parser: MySqlSqlParser,
) -> None:
    parsed = parser.parse(SqlInput.inline("  SELECT * FROM items;  "))

    assert parsed.original_sql == "  SELECT * FROM items;  "
    assert parsed.normalized_sql == "SELECT * FROM items"
    assert parsed.statement_type is SqlStatementType.SELECT
    assert parsed.is_read_only is True
    assert parsed.is_write is False
    assert parsed.requires_explicit_transaction is False


def test_parser_rejects_multiple_statements(parser: MySqlSqlParser) -> None:
    with pytest.raises(SqlParseError) as error:
        parser.parse(SqlText("SELECT 1; SELECT 2"))

    assert error.value.reason is SqlParseReason.MULTIPLE_STATEMENTS


def test_parser_rejects_repeated_terminal_delimiters(parser: MySqlSqlParser) -> None:
    with pytest.raises(SqlParseError) as error:
        parser.parse(SqlText("SELECT 1;;"))

    assert error.value.reason is SqlParseReason.MULTIPLE_STATEMENTS


@pytest.mark.parametrize(
    ("sql", "statement_type"),
    [
        ("SELECT 1", SqlStatementType.SELECT),
        ("SHOW TABLES", SqlStatementType.SHOW),
        ("DESCRIBE items", SqlStatementType.DESCRIBE),
        ("DESC items", SqlStatementType.DESCRIBE),
        ("EXPLAIN SELECT 1", SqlStatementType.EXPLAIN),
        ("EXPLAIN ANALYZE SELECT 1", SqlStatementType.EXPLAIN),
        ("INSERT INTO items(name) VALUES (%s)", SqlStatementType.INSERT),
        ("UPDATE items SET name = %s", SqlStatementType.UPDATE),
        ("DELETE FROM items", SqlStatementType.DELETE),
        ("CREATE TABLE items (id INT)", SqlStatementType.DDL),
        ("ALTER TABLE items ADD COLUMN name VARCHAR(32)", SqlStatementType.DDL),
        ("DROP TABLE items", SqlStatementType.DDL),
        ("TRUNCATE TABLE items", SqlStatementType.DDL),
    ],
)
def test_parser_classifies_supported_mysql_statements(
    parser: MySqlSqlParser,
    sql: str,
    statement_type: SqlStatementType,
) -> None:
    parsed = parser.parse(SqlText(sql))

    assert parsed.statement_type is statement_type
    assert parsed.is_read_only is (statement_type in {
        SqlStatementType.SELECT,
        SqlStatementType.SHOW,
        SqlStatementType.DESCRIBE,
        SqlStatementType.EXPLAIN,
    })
    assert parsed.is_write is not parsed.is_read_only


def test_parser_marks_explain_analyze_without_rewriting_it(
    parser: MySqlSqlParser,
) -> None:
    parsed = parser.parse(SqlText("EXPLAIN ANALYZE SELECT 1;"))

    assert parsed.is_explain_analyze is True
    assert parsed.normalized_sql == "EXPLAIN ANALYZE SELECT 1"


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 'value;still-one-statement'",
        "SELECT 1 /* a semicolon ; in a comment */;",
        "-- a semicolon ; in a comment\nSELECT 1;",
    ],
)
def test_parser_does_not_split_semicolons_in_literals_or_comments(
    parser: MySqlSqlParser,
    sql: str,
) -> None:
    parsed = parser.parse(SqlText(sql))

    assert parsed.statement_type is SqlStatementType.SELECT


def test_parser_maps_sqlglot_syntax_errors_to_typed_error(
    parser: MySqlSqlParser,
) -> None:
    with pytest.raises(SqlParseError) as error:
        parser.parse(SqlText("SELECT ("))

    assert error.value.reason is SqlParseReason.SYNTAX_ERROR
    assert "SELECT (" not in str(error.value)


def test_parser_rejects_valid_but_unsupported_statement(
    parser: MySqlSqlParser,
) -> None:
    with pytest.raises(UnsupportedSqlError) as error:
        parser.parse(SqlText("CALL refresh_items()"))

    assert "refresh_items" not in str(error.value)
