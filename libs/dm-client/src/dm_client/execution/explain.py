"""Text execution-plan retrieval that never executes the explained SQL."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from dm_client.domain.enums import SqlStatementType
from dm_client.domain.errors import InvalidArgumentError
from dm_client.domain.results import PLAN_FORMAT_TEXT, ExplainResult, TargetMetadata
from dm_client.execution.plan import parse_plan
from dm_client.execution.tabular import build_metadata
from dm_client.sql.parser import strip_explain_prefix

if TYPE_CHECKING:
    from dm_client.domain.requests import ExplainRequest, ParsedSql
    from dm_client.ports.driver import DmConnection

EMPTY_EXPLAIN_SQL_MESSAGE = "EXPLAIN requires a SQL statement after the EXPLAIN keyword"


def run_explain(
    connection: DmConnection,
    request: ExplainRequest,
    parsed: ParsedSql,
    target_label: str,
    *,
    target: TargetMetadata | None = None,
) -> ExplainResult:
    """Return the authoritative plan text and best-effort parsed nodes."""

    del parsed  # the session has already parsed and policy-checked the statement
    sql = str(strip_explain_prefix(str(request.sql.text))).strip()
    if not sql:
        raise InvalidArgumentError(EMPTY_EXPLAIN_SQL_MESSAGE)

    started_at = datetime.now(timezone.utc)
    resolved_target = target or TargetMetadata(
        label=target_label,
        schema=connection.current_schema,
        server_version=connection.server_version,
    )
    plan_text = connection.explain(sql)
    parsed_plan = parse_plan(plan_text)
    metadata = build_metadata(SqlStatementType.EXPLAIN, started_at, resolved_target)
    return ExplainResult(
        format=PLAN_FORMAT_TEXT,
        plan_text=parsed_plan.plan_text,
        nodes=parsed_plan.nodes,
        parse_status=parsed_plan.parse_status,
        parse_warning=parsed_plan.parse_warning,
        metadata=metadata,
    )


__all__ = ["EMPTY_EXPLAIN_SQL_MESSAGE", "run_explain"]
