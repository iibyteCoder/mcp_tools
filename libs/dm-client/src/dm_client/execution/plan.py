"""Best-effort parsing of the text execution plans returned by DM.

The plan text is authoritative. Parsing only extracts the line number, the
relative indentation depth, the operator name, the optional ``[cost, rows,
bytes]`` estimate and the optional trailing detail; unparseable lines degrade
the result to ``partial`` instead of failing the command.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from dm_client.domain.enums import PlanParseStatus
from dm_client.domain.results import PlanNode

PLAN_INDENT_WIDTH: Final[int] = 2

_PLAN_LINE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^\s*(?P<line>\d+)(?P<gap>\s+)(?P<body>#.*)$"
)
_LINE_NUMBER_PATTERN: Final[re.Pattern[str]] = re.compile(r"^\s*(?P<line>\d+)\b")
_OPERATION_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^#(?P<operation>[^:]*?)(?::\s*(?P<rest>.*))?$"
)
_METRICS_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^\[(?P<values>[^\]]*)\](?:;\s*(?P<detail>.*))?$"
)
_METRIC_SEPARATOR: Final[str] = ","
_METRIC_PART_COUNT: Final[int] = 3


@dataclass(frozen=True, slots=True, kw_only=True)
class ParsedPlan:
    """One plan body with its best-effort parsed operator nodes."""

    plan_text: str
    nodes: tuple[PlanNode, ...]
    parse_status: PlanParseStatus
    parse_warning: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class _PlanLine:
    """The structural part of one plan line before estimate parsing."""

    line: int
    hash_column: int
    body: str
    operation: str
    rest: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class _PlanEstimate:
    """The optional numeric estimate and trailing detail of one operator."""

    cost: float | None = None
    estimated_rows: int | None = None
    estimated_bytes: int | None = None
    detail: str | None = None


def parse_plan(plan_text: str) -> ParsedPlan:
    """Parse a DM text plan without ever consulting a driver or database."""

    body_lines = _plan_body_lines(plan_text)
    plan_body = "\n".join(body_lines)
    if not body_lines:
        return ParsedPlan(
            plan_text=plan_body,
            nodes=(),
            parse_status=PlanParseStatus.FAILED,
            parse_warning="plan text is empty",
        )

    first_hash_column = _first_hash_column(body_lines)
    nodes: list[PlanNode] = []
    first_unmatched_line: int | None = None
    for position, raw_line in enumerate(body_lines, start=1):
        if not raw_line.strip():
            continue
        plan_line = _parse_plan_line(raw_line)
        if plan_line is None:
            if first_unmatched_line is None:
                first_unmatched_line = _unmatched_line_number(raw_line, position)
            continue
        nodes.append(_build_node(plan_line, first_hash_column))

    if not nodes:
        warning = "no plan lines could be parsed"
        if first_unmatched_line is not None:
            warning = f"line {first_unmatched_line} could not be parsed"
        return ParsedPlan(
            plan_text=plan_body,
            nodes=(),
            parse_status=PlanParseStatus.FAILED,
            parse_warning=warning,
        )
    if first_unmatched_line is not None:
        return ParsedPlan(
            plan_text=plan_body,
            nodes=tuple(nodes),
            parse_status=PlanParseStatus.PARTIAL,
            parse_warning=f"line {first_unmatched_line} could not be parsed",
        )
    return ParsedPlan(
        plan_text=plan_body,
        nodes=tuple(nodes),
        parse_status=PlanParseStatus.PARSED,
        parse_warning=None,
    )


def _plan_body_lines(plan_text: str) -> tuple[str, ...]:
    lines = plan_text.splitlines()
    start = 0
    end = len(lines)
    while start < end and not lines[start].strip():
        start += 1
    while end > start and not lines[end - 1].strip():
        end -= 1
    return tuple(lines[start:end])


def _first_hash_column(body_lines: tuple[str, ...]) -> int | None:
    for raw_line in body_lines:
        column = raw_line.find("#")
        if column >= 0:
            return column
    return None


def _parse_plan_line(raw_line: str) -> _PlanLine | None:
    match = _PLAN_LINE_PATTERN.match(raw_line)
    if match is None:
        return None
    body = match.group("body")
    operation_match = _OPERATION_PATTERN.match(body)
    if operation_match is None:
        return None
    operation = operation_match.group("operation").strip()
    if not operation:
        return None
    return _PlanLine(
        line=int(match.group("line")),
        hash_column=match.start("body"),
        body=body,
        operation=operation,
        rest=operation_match.group("rest"),
    )


def _build_node(plan_line: _PlanLine, first_hash_column: int | None) -> PlanNode:
    estimate = _estimate(plan_line.rest)
    depth = 0
    if first_hash_column is not None:
        depth = max(0, (plan_line.hash_column - first_hash_column) // PLAN_INDENT_WIDTH)
    return PlanNode(
        line=plan_line.line,
        depth=depth,
        operation=plan_line.operation,
        text=plan_line.body.strip(),
        cost=estimate.cost,
        estimated_rows=estimate.estimated_rows,
        estimated_bytes=estimate.estimated_bytes,
        detail=estimate.detail,
    )


def _estimate(rest: str | None) -> _PlanEstimate:
    if rest is None or not rest.strip():
        return _PlanEstimate()
    stripped_rest = rest.strip()
    metrics = _METRICS_PATTERN.match(stripped_rest)
    if metrics is None:
        return _PlanEstimate(detail=stripped_rest)
    detail = _optional_text(metrics.group("detail"))
    return _metric_estimate(metrics.group("values"), detail)


def _metric_estimate(values: str, detail: str | None) -> _PlanEstimate:
    parts = [part.strip() for part in values.split(_METRIC_SEPARATOR)]
    if len(parts) != _METRIC_PART_COUNT:
        return _PlanEstimate(detail=detail)
    try:
        return _PlanEstimate(
            cost=float(parts[0]),
            estimated_rows=int(parts[1]),
            estimated_bytes=int(parts[2]),
            detail=detail,
        )
    except ValueError:
        return _PlanEstimate(detail=detail)


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped if stripped else None


def _unmatched_line_number(raw_line: str, position: int) -> int:
    match = _LINE_NUMBER_PATTERN.match(raw_line)
    if match is None:
        return position
    return int(match.group("line"))


__all__ = ["PLAN_INDENT_WIDTH", "ParsedPlan", "parse_plan"]
