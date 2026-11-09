"""One ``DBMS_STATS`` table analysis with explicit auto-commit semantics.

``GATHER_TABLE_STATS`` persists its effect even when the session later rolls
back, so this feature treats it as auto-commit: it commits after the call and
reports an explicit outcome instead of a caller-requested transaction mode.
Statistics are captured before and after the analysis so the caller can see the
observed change rather than an assumed one.
"""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Final

from dm_client.domain.enums import SqlStatementType, WriteOutcome
from dm_client.domain.errors import ClientError, QueryError, WriteError
from dm_client.domain.results import (
    AnalyzeOptions,
    AnalyzeResult,
    AnalyzeStatistics,
    TargetMetadata,
)
from dm_client.execution.inspection_support import (
    effective_schema,
    fetch_all,
    resolve_target,
    text_value,
)
from dm_client.execution.tabular import build_metadata
from dm_client.sql.analyze_queries import (
    build_gather_table_stats_call,
    build_table_stats_query,
)

if TYPE_CHECKING:
    from dm_client.domain.requests import SchemaAnalyzeRequest
    from dm_client.domain.values import DatabaseParameters, DatabaseValue
    from dm_client.ports.driver import DmConnection, DriverRow

_STATISTICS_ROW_WIDTH: Final[int] = 2


def run_schema_analyze(
    connection: DmConnection,
    request: SchemaAnalyzeRequest,
    target_label: str,
    *,
    target: TargetMetadata | None = None,
) -> AnalyzeResult:
    """Collect table or partition statistics and report the observed outcome."""

    started_at = datetime.now(timezone.utc)
    resolved_target = resolve_target(connection, target_label, target)
    schema = effective_schema(connection, request.schema)
    table = request.table.value
    partition = request.partition

    before = _read_statistics(connection, schema, table, partition)
    try:
        _gather_statistics(connection, request, schema, table)
    except ClientError:
        raise
    except BaseException as exc:
        raise WriteError(
            _failure_message("DM statistics collection failed", exc),
            outcome=WriteOutcome.DETERMINED_FAILURE,
        ) from exc

    try:
        connection.commit()
    except BaseException as exc:
        raise WriteError(
            _failure_message("DM statistics commit outcome is unknown", exc),
            outcome=WriteOutcome.UNKNOWN,
            hint=exc.hint if isinstance(exc, ClientError) else None,
        ) from exc

    after = _read_statistics(connection, schema, table, partition)
    options = AnalyzeOptions(
        estimate_percent=request.estimate_percent,
        cascade=request.cascade,
        degree=request.degree,
    )
    metadata = build_metadata(SqlStatementType.CALL, started_at, resolved_target)
    return AnalyzeResult(
        schema=schema,
        table=table,
        partition=partition,
        options=options,
        before=before,
        after=after,
        outcome=WriteOutcome.COMMITTED,
        duration_ms=metadata.duration_ms,
        metadata=metadata,
    )


def _gather_statistics(
    connection: DmConnection,
    request: SchemaAnalyzeRequest,
    schema: str,
    table: str,
) -> None:
    """Run the nine-argument ``GATHER_TABLE_STATS`` call once."""

    cursor = connection.cursor()
    try:
        cursor.execute(build_gather_table_stats_call(), _call_parameters(request, schema, table))
    finally:
        cursor.close()


def _read_statistics(
    connection: DmConnection,
    schema: str,
    table: str,
    partition: str | None,
) -> AnalyzeStatistics:
    """Read the table-level or partition-level statistics snapshot."""

    partitioned = partition is not None
    parameters: DatabaseParameters = (schema, table, partition) if partitioned else (schema, table)
    cursor = connection.cursor()
    try:
        cursor.execute(build_table_stats_query(partitioned=partitioned), parameters)
        rows = fetch_all(cursor)
    finally:
        cursor.close()
    return _statistics(rows)


def _statistics(rows: tuple[DriverRow, ...]) -> AnalyzeStatistics:
    """Convert the first statistics row, or report an absent snapshot."""

    if not rows:
        return AnalyzeStatistics()
    row = rows[0]
    if len(row) < _STATISTICS_ROW_WIDTH:
        raise QueryError("ALL_TAB_STATISTICS returned an unexpected row shape")
    return AnalyzeStatistics(
        last_analyzed=_analyzed_at(row[1]),
        num_rows=_row_count(row[0]),
    )


def _row_count(value: DatabaseValue) -> int | None:
    """Convert a driver row-count value to an integer when it is numeric."""

    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, (float, Decimal)):
        return int(value)
    try:
        return int(text_value(value).strip())
    except ValueError:
        return None


def _analyzed_at(value: DatabaseValue) -> datetime | None:
    """Convert a driver analysis timestamp to a datetime when it is temporal."""

    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, time.min)
    return None


def _call_parameters(
    request: SchemaAnalyzeRequest,
    schema: str,
    table: str,
) -> DatabaseParameters:
    """Bind the nine ``GATHER_TABLE_STATS`` arguments in call order."""

    return (
        schema,
        table,
        request.partition,
        request.estimate_percent,
        False,
        None,
        request.degree,
        None,
        request.cascade,
    )


def _failure_message(prefix: str, exc: BaseException) -> str:
    message = str(exc).strip() or exc.__class__.__name__
    return f"{prefix}: {message}"


__all__ = ["run_schema_analyze"]
