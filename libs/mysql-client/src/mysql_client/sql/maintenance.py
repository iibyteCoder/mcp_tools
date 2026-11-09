"""SQL construction for MySQL table maintenance statements."""

from __future__ import annotations

from typing import TYPE_CHECKING

from mysql_client.domain.values import SqlText

if TYPE_CHECKING:
    from mysql_client.domain.requests import AnalyzeTableRequest


def build_analyze_table_sql(request: AnalyzeTableRequest) -> SqlText:
    """Build one ``ANALYZE TABLE`` statement with quoted identifiers."""

    table = _quote_identifier(request.table.value)
    if request.database is None:
        return SqlText(f"ANALYZE TABLE {table}")
    return SqlText(f"ANALYZE TABLE {_quote_identifier(request.database.value)}.{table}")


def _quote_identifier(value: str) -> str:
    return f"`{value.replace('`', '``')}`"


__all__ = ["build_analyze_table_sql"]
