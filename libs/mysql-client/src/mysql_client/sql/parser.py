"""Strict MySQL SQL parsing at the driver-independent domain boundary."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise

from sqlglot import Expression, exp, parse
from sqlglot.errors import ErrorLevel, SqlglotError
from sqlglot.tokens import Token, Tokenizer, TokenType

from mysql_client.domain.enums import (
    ExplainFormat,
    SqlParseReason,
    SqlReadEffect,
    SqlSideEffectFunction,
    SqlStatementType,
)
from mysql_client.domain.errors import SqlParseError, UnsupportedSqlError
from mysql_client.domain.requests import ParsedSql, SqlInput
from mysql_client.domain.values import SqlText

SqlSource = SqlInput | SqlText

_EXPLAIN_ANALYZE_STYLE = "ANALYZE"
_EXPLAIN_FORMATS: dict[str, ExplainFormat] = {
    explain_format.value.upper(): explain_format for explain_format in ExplainFormat
}


@dataclass(frozen=True, slots=True)
class _TextReplacement:
    """One parser-only replacement for a DB-API placeholder."""

    start: int
    end: int
    replacement: str


class MySqlSqlParser:
    """Parse exactly one MySQL statement without changing its execution text."""

    def parse(self, sql: SqlSource) -> ParsedSql:
        """Validate, classify, and normalize one SQL input.

        ``normalized_sql`` only removes surrounding whitespace and one allowed
        terminal delimiter. It never adds a wrapper, pagination, or other SQL.
        """

        original_sql = self._source_text(sql)
        stripped_sql = original_sql.strip()
        if not stripped_sql:
            raise SqlParseError(
                "SQL 输入不能为空",
                reason=SqlParseReason.EMPTY,
            )

        if not self._without_terminal_delimiter(stripped_sql).strip():
            raise SqlParseError(
                "SQL 输入不能为空",
                reason=SqlParseReason.EMPTY,
            )

        parser_sql = self._parser_text(stripped_sql)
        expression = self._parse_one(parser_sql)
        statement_type = self._statement_type(expression, stripped_sql)
        normalized_sql = self._without_terminal_delimiter(stripped_sql)
        is_explain_analyze = self._is_explain_analyze(expression, statement_type)
        is_read_only = statement_type in {
            SqlStatementType.SELECT,
            SqlStatementType.SHOW,
            SqlStatementType.DESCRIBE,
            SqlStatementType.EXPLAIN,
        }
        is_write = statement_type in {
            SqlStatementType.INSERT,
            SqlStatementType.UPDATE,
            SqlStatementType.DELETE,
            SqlStatementType.DDL,
        }
        return ParsedSql(
            original_sql=SqlText(original_sql),
            normalized_sql=SqlText(normalized_sql),
            statement_type=statement_type,
            is_read_only=is_read_only,
            is_write=is_write,
            requires_explicit_transaction=is_write,
            is_explain_analyze=is_explain_analyze,
            explain_format=self._explain_format(
                expression,
                statement_type,
                is_analyze=is_explain_analyze,
            ),
            read_effect=self._read_effect(expression, statement_type),
        )

    @staticmethod
    def _source_text(sql: SqlSource) -> str:
        if isinstance(sql, SqlInput):
            return str(sql.text)
        return str(sql)

    @staticmethod
    def _parser_text(sql: str) -> str:
        """Make MySQL ``%s`` parameters parseable without changing user SQL."""

        tokens = MySqlSqlParser._tokenize(sql)
        replacements: list[_TextReplacement] = []
        for current, following in pairwise(tokens):
            if (
                current.token_type is TokenType.MOD
                and following.token_type is TokenType.VAR
                and following.text.casefold() == "s"
                and current.end + 1 == following.start
            ):
                replacements.append(
                    _TextReplacement(
                        start=current.start,
                        end=following.end + 1,
                        replacement="?",
                    )
                )
        if not replacements:
            return sql
        parts: list[str] = []
        cursor = 0
        for replacement in replacements:
            parts.append(sql[cursor : replacement.start])
            parts.append(replacement.replacement)
            cursor = replacement.end
        parts.append(sql[cursor:])
        return "".join(parts)

    @staticmethod
    def _parse_one(sql: str) -> Expression:
        try:
            expressions = tuple(
                parse(sql, read="mysql", error_level=ErrorLevel.IMMEDIATE)
            )
        except SqlglotError as exc:
            raise SqlParseError(
                "SQL 语法解析失败",
                reason=SqlParseReason.SYNTAX_ERROR,
            ) from exc
        if len(expressions) != 1 or expressions[0] is None:
            raise SqlParseError(
                "一次请求只能包含一条 SQL 语句",
                reason=SqlParseReason.MULTIPLE_STATEMENTS,
            )
        return expressions[0]

    @staticmethod
    def _tokenize(sql: str) -> tuple[Token, ...]:
        try:
            return tuple(Tokenizer(dialect="mysql").tokenize(sql))
        except SqlglotError as exc:
            raise SqlParseError(
                "SQL 语法解析失败",
                reason=SqlParseReason.SYNTAX_ERROR,
            ) from exc

    @staticmethod
    def _statement_type(expression: Expression, source: str) -> SqlStatementType:
        if isinstance(expression, exp.Select):
            return SqlStatementType.SELECT
        if isinstance(expression, exp.Show):
            return SqlStatementType.SHOW
        if isinstance(expression, exp.Describe):
            first_keyword = MySqlSqlParser._first_keyword(source)
            if first_keyword == SqlStatementType.EXPLAIN.value.upper():
                return SqlStatementType.EXPLAIN
            return SqlStatementType.DESCRIBE
        if isinstance(expression, exp.Insert):
            return SqlStatementType.INSERT
        if isinstance(expression, exp.Update):
            return SqlStatementType.UPDATE
        if isinstance(expression, exp.Delete):
            return SqlStatementType.DELETE
        if isinstance(expression, (exp.Create, exp.Alter, exp.Drop, exp.TruncateTable)):
            return SqlStatementType.DDL
        raise UnsupportedSqlError("SQL 语句类型不受 mysql-client 执行策略支持")

    @staticmethod
    def _first_keyword(sql: str) -> str:
        tokens = MySqlSqlParser._tokenize(sql)
        if not tokens:
            return ""
        return tokens[0].text.upper()

    @staticmethod
    def _without_terminal_delimiter(sql: str) -> str:
        if sql.endswith(";"):
            return sql[:-1].rstrip()
        return sql

    @staticmethod
    def _is_explain_analyze(expression: Expression, statement_type: SqlStatementType) -> bool:
        if statement_type is not SqlStatementType.EXPLAIN:
            return False
        return str(expression.args.get("style", "")).upper() == _EXPLAIN_ANALYZE_STYLE

    @staticmethod
    def _explain_format(
        expression: Expression,
        statement_type: SqlStatementType,
        *,
        is_analyze: bool,
    ) -> ExplainFormat | None:
        if statement_type is not SqlStatementType.EXPLAIN:
            return None
        declared_format = MySqlSqlParser._declared_explain_format(expression)
        if is_analyze:
            if declared_format is not None and declared_format is not ExplainFormat.TREE:
                raise UnsupportedSqlError(
                    "EXPLAIN ANALYZE 仅支持 TREE 格式",
                    hint="移除 FORMAT 子句或改用 FORMAT=TREE",
                )
            return ExplainFormat.TREE
        return declared_format if declared_format is not None else ExplainFormat.TRADITIONAL

    @staticmethod
    def _declared_explain_format(expression: Expression) -> ExplainFormat | None:
        property_expression: object = expression.args.get("format")
        if property_expression is None:
            return None
        if not isinstance(property_expression, exp.FileFormatProperty):
            raise UnsupportedSqlError("无法识别的 EXPLAIN FORMAT 子句")
        value_expression: object = property_expression.this
        if not isinstance(value_expression, exp.Var):
            raise UnsupportedSqlError(
                "EXPLAIN FORMAT 值必须是 TRADITIONAL、JSON 或 TREE",
                hint="FORMAT 后直接写格式名, 不要加引号",
            )
        raw_value: object = value_expression.this
        if not isinstance(raw_value, str):
            raise UnsupportedSqlError("无法识别的 EXPLAIN FORMAT 值")
        explain_format = _EXPLAIN_FORMATS.get(raw_value.upper())
        if explain_format is None:
            raise UnsupportedSqlError(
                "MySQL 不支持该 EXPLAIN FORMAT 值",
                hint="仅支持 TRADITIONAL、JSON 和 TREE",
            )
        return explain_format

    @staticmethod
    def _read_effect(expression: Expression, statement_type: SqlStatementType) -> SqlReadEffect:
        if statement_type not in {
            SqlStatementType.SELECT,
            SqlStatementType.SHOW,
            SqlStatementType.DESCRIBE,
        }:
            return SqlReadEffect.NONE
        if expression.find(exp.Lock) is not None:
            return SqlReadEffect.LOCKING
        if expression.find(exp.PropertyEQ) is not None:
            return SqlReadEffect.SIDE_EFFECT
        for function in expression.find_all(exp.Anonymous):
            try:
                SqlSideEffectFunction(function.name.upper())
            except ValueError:
                continue
            return SqlReadEffect.SIDE_EFFECT
        return SqlReadEffect.NONE
