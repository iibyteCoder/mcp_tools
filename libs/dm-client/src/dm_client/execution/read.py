"""One bounded read executed without rewriting the caller's SQL."""

from __future__ import annotations

from contextlib import suppress
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from dm_client.domain.results import QueryResult, TargetMetadata
from dm_client.execution.tabular import (
    DEFAULT_MAX_BYTES,
    DEFAULT_MAX_ROWS,
    build_metadata,
    build_query_result,
)

if TYPE_CHECKING:
    from dm_client.domain.requests import ParsedSql, ReadRequest
    from dm_client.ports.driver import DmConnection


def run_read(
    connection: DmConnection,
    request: ReadRequest,
    parsed: ParsedSql,
    target_label: str,
    *,
    target: TargetMetadata | None = None,
) -> QueryResult:
    """Execute one read and materialize a bounded tabular result."""

    started_at = datetime.now(timezone.utc)
    resolved_target = target or TargetMetadata(
        label=target_label,
        schema=connection.current_schema,
        server_version=connection.server_version,
    )
    max_rows = request.max_rows if request.max_rows is not None else DEFAULT_MAX_ROWS
    max_bytes = request.max_bytes if request.max_bytes is not None else DEFAULT_MAX_BYTES

    cursor = connection.cursor()
    try:
        cursor.execute(str(request.sql.text), request.parameters)
        result = build_query_result(
            cursor,
            build_metadata(parsed.statement_type, started_at, resolved_target),
            max_rows,
            max_bytes,
        )
    except BaseException:
        with suppress(BaseException):
            cursor.close()
        raise
    else:
        cursor.close()

    metadata = build_metadata(
        parsed.statement_type,
        started_at,
        resolved_target,
        row_count=len(result.rows),
    )
    return QueryResult(
        columns=result.columns,
        rows=result.rows,
        metadata=metadata,
        truncated=result.truncated,
    )


__all__ = ["run_read"]
