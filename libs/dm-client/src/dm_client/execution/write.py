"""One-statement write execution with explicit commit semantics."""

from __future__ import annotations

from contextlib import suppress
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from dm_client.domain.enums import SqlStatementType, TransactionAction, WriteOutcome
from dm_client.domain.errors import ClientError, WriteError
from dm_client.domain.results import TargetMetadata, WriteResult
from dm_client.execution.tabular import build_metadata

if TYPE_CHECKING:
    from dm_client.domain.requests import ParsedSql, WriteRequest
    from dm_client.ports.driver import DmConnection

_REDACTED_SQL = "<sql>"


def run_write(
    connection: DmConnection,
    request: WriteRequest,
    parsed: ParsedSql,
    target_label: str,
    *,
    target: TargetMetadata | None = None,
) -> WriteResult:
    """Execute one write and make its transaction result explicit."""

    started_at = datetime.now(timezone.utc)
    resolved_target = target or TargetMetadata(
        label=target_label,
        schema=connection.current_schema,
        server_version=connection.server_version,
    )
    sql_text = str(request.sql.text)
    is_ddl = parsed.statement_type is SqlStatementType.DDL

    cursor = connection.cursor()
    try:
        cursor.execute(sql_text, request.parameters)
        affected_rows = max(cursor.rowcount, 0)
    except ClientError:
        with suppress(BaseException):
            cursor.close()
        raise
    except BaseException as exc:
        with suppress(BaseException):
            cursor.close()
        raise WriteError(
            _failure_message("DM write execution failed", exc, sql_text),
            outcome=WriteOutcome.DETERMINED_FAILURE,
            hint=_error_hint(exc),
        ) from exc
    with suppress(BaseException):
        cursor.close()

    try:
        if is_ddl or request.transaction is TransactionAction.COMMIT:
            connection.commit()
            outcome = WriteOutcome.COMMITTED
        else:
            connection.rollback()
            outcome = WriteOutcome.ROLLED_BACK
    except BaseException as exc:
        raise WriteError(
            _failure_message("DM write transaction outcome is unknown", exc, sql_text),
            outcome=WriteOutcome.UNKNOWN,
            hint=_error_hint(exc),
        ) from exc

    metadata = build_metadata(
        parsed.statement_type,
        started_at,
        resolved_target,
        affected_rows=affected_rows,
    )
    return WriteResult(
        affected_rows=affected_rows,
        metadata=metadata,
        outcome=outcome,
        ddl_auto_commit=is_ddl,
        generated_values=(),
    )


def _failure_message(prefix: str, exc: BaseException, sql: str) -> str:
    message = str(exc).strip() or exc.__class__.__name__
    stripped_sql = sql.strip()
    if stripped_sql:
        message = message.replace(sql, _REDACTED_SQL).replace(stripped_sql, _REDACTED_SQL)
    return f"{prefix}: {message}" if message else prefix


def _error_hint(exc: BaseException) -> str | None:
    return exc.hint if isinstance(exc, ClientError) else None


__all__ = ["run_write"]
