"""Typed construction of explicit ``EXPLAIN ANALYZE`` statements."""

from __future__ import annotations

from dataclasses import dataclass

from mysql_client import (
    ExecutionPolicy,
    InternalError,
    InvalidArgumentError,
    MySqlSqlParser,
    ParsedSql,
    SqlInput,
    SqlStatementType,
    SqlText,
    UnsupportedSqlError,
    validate_execution_policy,
)

_EXPLAIN_ANALYZE_PREFIX = "EXPLAIN ANALYZE "


@dataclass(frozen=True, slots=True, kw_only=True)
class ExplainAnalyzeStatement:
    """The built server statement plus its parsed EXPLAIN ANALYZE facts."""

    sql: SqlInput
    parsed: ParsedSql


def build_explain_analyze(sql: SqlInput) -> ExplainAnalyzeStatement:
    """Wrap one read-only SELECT/WITH query in exactly one EXPLAIN ANALYZE prefix."""

    parser = MySqlSqlParser()
    parsed = parser.parse(sql)
    if parsed.statement_type is SqlStatementType.EXPLAIN:
        raise InvalidArgumentError(
            "--analyze 需要原始 SELECT/WITH SQL, 不能是 EXPLAIN 语句",
            hint="省略 EXPLAIN 或 EXPLAIN ANALYZE, 该选项会自行添加前缀",
        )
    validate_execution_policy(parsed, ExecutionPolicy.READ_ONLY)
    if parsed.statement_type is not SqlStatementType.SELECT:
        raise UnsupportedSqlError(
            "sql explain --analyze 仅支持 SELECT/WITH 查询",
            hint="SHOW、DESCRIBE 和其他语句不能与 --analyze 一起使用",
        )
    built_sql = SqlInput.inline(SqlText(f"{_EXPLAIN_ANALYZE_PREFIX}{parsed.normalized_sql}"))
    analyzed = parser.parse(built_sql)
    if analyzed.statement_type is not SqlStatementType.EXPLAIN or not analyzed.is_explain_analyze:
        raise InternalError("无法构造 EXPLAIN ANALYZE 语句")
    return ExplainAnalyzeStatement(sql=built_sql, parsed=analyzed)


__all__ = ["ExplainAnalyzeStatement", "build_explain_analyze"]
