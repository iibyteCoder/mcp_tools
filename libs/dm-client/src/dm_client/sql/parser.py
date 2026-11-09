"""Local, driver-free parser for exactly one DM SQL statement."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from dm_client.domain.enums import SqlParseReason, SqlReadEffect, SqlStatementType
from dm_client.domain.errors import SqlParseError
from dm_client.domain.requests import ParsedSql, SqlInput
from dm_client.domain.values import SqlText

SqlSource = SqlInput | str

_WORD_PATTERN: Final[re.Pattern[str]] = re.compile(r"[A-Za-z_][A-Za-z0-9_$#]*")

_DIRECT_STATEMENT_TYPES: Final[dict[str, SqlStatementType]] = {
    "SELECT": SqlStatementType.SELECT,
    "SHOW": SqlStatementType.SHOW,
    "DESCRIBE": SqlStatementType.DESCRIBE,
    "DESC": SqlStatementType.DESCRIBE,
    "EXPLAIN": SqlStatementType.EXPLAIN,
    "INSERT": SqlStatementType.INSERT,
    "UPDATE": SqlStatementType.UPDATE,
    "DELETE": SqlStatementType.DELETE,
    "MERGE": SqlStatementType.MERGE,
    "CALL": SqlStatementType.CALL,
    "SET": SqlStatementType.SET,
}
_DDL_KEYWORDS: Final[frozenset[str]] = frozenset(
    {"CREATE", "ALTER", "DROP", "TRUNCATE", "RENAME", "COMMENT", "GRANT", "REVOKE"}
)
_CTE_MAIN_STATEMENTS: Final[dict[str, SqlStatementType]] = {
    "SELECT": SqlStatementType.SELECT,
    "INSERT": SqlStatementType.INSERT,
    "UPDATE": SqlStatementType.UPDATE,
    "DELETE": SqlStatementType.DELETE,
    "MERGE": SqlStatementType.MERGE,
}
_READ_ONLY_STATEMENTS: Final[frozenset[SqlStatementType]] = frozenset(
    {
        SqlStatementType.SELECT,
        SqlStatementType.SHOW,
        SqlStatementType.DESCRIBE,
        SqlStatementType.EXPLAIN,
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
_LOCKING_WORDS: Final[frozenset[str]] = frozenset({"UPDATE", "SHARE"})


@dataclass(frozen=True, slots=True, kw_only=True)
class _SqlToken:
    text: str
    upper: str
    start: int
    end: int
    depth: int


class DmSqlParser:
    """Validate and classify one statement without changing its execution text."""

    def parse(self, sql: SqlSource) -> ParsedSql:
        """Return the typed parse result or raise :class:`SqlParseError`."""

        original_sql = _source_text(sql)
        stripped_sql = original_sql.strip()
        if not stripped_sql:
            raise SqlParseError("SQL input must not be empty", reason=SqlParseReason.EMPTY)

        masked_sql = _mask_sql(stripped_sql)
        if not masked_sql.strip():
            raise SqlParseError("SQL input must not be empty", reason=SqlParseReason.EMPTY)

        delimiter_position = _terminal_delimiter_position(masked_sql)
        if delimiter_position is not None:
            masked_body = masked_sql[:delimiter_position] + masked_sql[delimiter_position + 1 :]
            if not masked_body.strip():
                raise SqlParseError("SQL input must not be empty", reason=SqlParseReason.EMPTY)

        normalized_sql = _normalized_text(stripped_sql, delimiter_position)
        tokens = _scan_tokens(masked_sql)
        top_level = tuple(token for token in tokens if token.depth == 0)
        statement_type = _statement_type(top_level)
        is_read_only = statement_type in _READ_ONLY_STATEMENTS
        is_write = statement_type in _WRITE_STATEMENTS

        return ParsedSql(
            original_sql=SqlText(original_sql),
            normalized_sql=SqlText(normalized_sql),
            statement_type=statement_type,
            is_read_only=is_read_only,
            is_write=is_write,
            requires_explicit_transaction=is_write,
            is_explain_analyze=_is_explain_analyze(top_level),
            read_effect=_read_effect(statement_type, top_level),
        )


def strip_explain_prefix(sql: SqlSource) -> SqlText:
    """Remove one leading ``EXPLAIN`` and optional ``ANALYZE`` token.

    Batch 3 explain execution uses this helper; no driver call is made here.
    """

    stripped_sql = _source_text(sql).strip()
    if not stripped_sql:
        return SqlText("")
    masked_sql = _mask_sql(stripped_sql)
    top_level = tuple(token for token in _scan_tokens(masked_sql) if token.depth == 0)
    if not top_level or top_level[0].upper != "EXPLAIN":
        return SqlText(stripped_sql)
    end = top_level[0].end
    if len(top_level) > 1 and top_level[1].upper == "ANALYZE":
        end = top_level[1].end
    return SqlText(stripped_sql[end:].strip())


def _source_text(sql: SqlSource) -> str:
    if isinstance(sql, SqlInput):
        return str(sql.text)
    return str(sql)


def _mask_sql(sql: str) -> str:
    """Blank literals and comments while preserving character positions.

    Doubled single quotes and doubled double quotes are the only escape forms
    recognized, matching the DM SQL dialect used by this client.
    """

    characters = list(sql)
    length = len(sql)
    index = 0
    while index < length:
        current = sql[index]
        if current == "'":
            end = _quoted_end(sql, index, quote="'")
            _blank(characters, index, end)
            index = end
        elif current == '"':
            end = _quoted_end(sql, index, quote='"')
            _blank(characters, index, end)
            index = end
        elif current == "-" and index + 1 < length and sql[index + 1] == "-":
            newline = sql.find("\n", index + 2)
            end = length if newline == -1 else newline
            _blank(characters, index, end)
            index = end
        elif current == "/" and index + 1 < length and sql[index + 1] == "*":
            closing = sql.find("*/", index + 2)
            if closing == -1:
                raise SqlParseError(
                    "block comment is not terminated",
                    reason=SqlParseReason.UNTERMINATED_COMMENT,
                )
            end = closing + 2
            _blank(characters, index, end)
            index = end
        else:
            index += 1
    return "".join(characters)


def _quoted_end(sql: str, start: int, *, quote: str) -> int:
    index = start + 1
    length = len(sql)
    while index < length:
        if sql[index] == quote:
            if index + 1 < length and sql[index + 1] == quote:
                index += 2
                continue
            return index + 1
        index += 1
    raise SqlParseError(
        "quoted literal or identifier is not terminated",
        reason=SqlParseReason.UNTERMINATED_QUOTE,
    )


def _blank(characters: list[str], start: int, end: int) -> None:
    for position in range(start, end):
        characters[position] = " "


def _terminal_delimiter_position(masked_sql: str) -> int | None:
    delimiter_count = masked_sql.count(";")
    if delimiter_count == 0:
        return None
    if delimiter_count > 1:
        raise SqlParseError(
            "exactly one SQL statement is allowed",
            reason=SqlParseReason.MULTIPLE_STATEMENTS,
        )
    position = masked_sql.index(";")
    if masked_sql[position + 1 :].strip():
        raise SqlParseError(
            "exactly one SQL statement is allowed",
            reason=SqlParseReason.MULTIPLE_STATEMENTS,
        )
    return position


def _normalized_text(stripped_sql: str, delimiter_position: int | None) -> str:
    if delimiter_position is None:
        return stripped_sql
    return (stripped_sql[:delimiter_position] + stripped_sql[delimiter_position + 1 :]).rstrip()


def _scan_tokens(masked_sql: str) -> tuple[_SqlToken, ...]:
    tokens: list[_SqlToken] = []
    depth = 0
    index = 0
    length = len(masked_sql)
    while index < length:
        current = masked_sql[index]
        if current == "(":
            depth += 1
            index += 1
            continue
        if current == ")":
            depth = max(0, depth - 1)
            index += 1
            continue
        match = _WORD_PATTERN.match(masked_sql, index)
        if match is not None:
            text = match.group(0)
            tokens.append(
                _SqlToken(
                    text=text,
                    upper=text.upper(),
                    start=index,
                    end=match.end(),
                    depth=depth,
                )
            )
            index = match.end()
            continue
        index += 1
    return tuple(tokens)


def _statement_type(top_level: tuple[_SqlToken, ...]) -> SqlStatementType:
    if not top_level:
        return SqlStatementType.OTHER
    first = top_level[0].upper
    direct = _DIRECT_STATEMENT_TYPES.get(first)
    if direct is not None:
        return direct
    if first in _DDL_KEYWORDS:
        return SqlStatementType.DDL
    if first == "WITH":
        for token in top_level[1:]:
            cte_main = _CTE_MAIN_STATEMENTS.get(token.upper)
            if cte_main is not None:
                return cte_main
        return SqlStatementType.SELECT
    return SqlStatementType.OTHER


def _is_explain_analyze(top_level: tuple[_SqlToken, ...]) -> bool:
    return (
        len(top_level) > 1
        and top_level[0].upper == "EXPLAIN"
        and top_level[1].upper == "ANALYZE"
    )


def _read_effect(
    statement_type: SqlStatementType,
    top_level: tuple[_SqlToken, ...],
) -> SqlReadEffect:
    if statement_type is SqlStatementType.SET:
        return SqlReadEffect.SESSION_STATE
    if statement_type is SqlStatementType.SELECT and _has_for_lock(top_level):
        return SqlReadEffect.LOCKING
    return SqlReadEffect.NONE


def _has_for_lock(top_level: tuple[_SqlToken, ...]) -> bool:
    for index in range(len(top_level) - 1):
        if top_level[index].upper == "FOR" and top_level[index + 1].upper in _LOCKING_WORDS:
            return True
    return False


__all__ = ["DmSqlParser", "SqlSource", "strip_explain_prefix"]
