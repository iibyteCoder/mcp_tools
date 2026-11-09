"""Unit tests for text execution-plan retrieval without SQL execution."""

from __future__ import annotations

import pytest

from dm_client.domain.enums import PlanParseStatus, SqlStatementType
from dm_client.domain.errors import InvalidArgumentError
from dm_client.domain.requests import ExplainRequest, SqlInput
from dm_client.domain.results import PLAN_FORMAT_TEXT, TargetMetadata
from dm_client.execution.explain import run_explain
from dm_client.sql.parser import DmSqlParser

SIMPLE_PLAN = "\n".join(
    (
        "1   #NSET2: [1, 1, 1]",
        "2     #PRJT2: [1, 1, 1]; exp_num(1)",
    )
)


class FakeConnection:
    server_version = "8.1.4.80"
    current_schema = "APP"

    def __init__(self, plan_text: str = SIMPLE_PLAN) -> None:
        self.plan_text = plan_text
        self.explained: list[str] = []
        self.cursor_calls = 0

    def explain(self, sql: str) -> str:
        self.explained.append(sql)
        return self.plan_text

    def cursor(self) -> object:
        self.cursor_calls += 1
        raise AssertionError("explain must never open a cursor")


def request_for(sql: str) -> ExplainRequest:
    return ExplainRequest(sql=SqlInput.inline(sql))


def test_run_explain_strips_the_prefix_parses_nodes_and_never_executes() -> None:
    connection = FakeConnection()
    request = request_for("  EXPLAIN SELECT 1 AS N FROM DUAL  ")
    parsed = DmSqlParser().parse(request.sql.text)

    result = run_explain(connection, request, parsed, "test")

    assert connection.explained == ["SELECT 1 AS N FROM DUAL"]
    assert connection.cursor_calls == 0
    assert result.format == PLAN_FORMAT_TEXT
    assert result.plan_text == SIMPLE_PLAN
    assert result.parse_status is PlanParseStatus.PARSED
    assert result.parse_warning is None
    assert [node.operation for node in result.nodes] == ["NSET2", "PRJT2"]
    assert result.metadata.statement_type is SqlStatementType.EXPLAIN
    assert result.metadata.row_count == 0
    assert result.metadata.target == TargetMetadata(
        label="test",
        schema="APP",
        server_version="8.1.4.80",
    )


def test_run_explain_without_a_prefix_passes_the_sql_unchanged() -> None:
    connection = FakeConnection()
    request = request_for("SELECT 1 AS N FROM DUAL")
    parsed = DmSqlParser().parse(request.sql.text)

    run_explain(connection, request, parsed, "test")

    assert connection.explained == ["SELECT 1 AS N FROM DUAL"]
    assert connection.cursor_calls == 0


def test_run_explain_reuses_an_explicit_target() -> None:
    connection = FakeConnection()
    request = request_for("SELECT 1 FROM DUAL")
    target = TargetMetadata(
        label="lot-01",
        host="127.0.0.1",
        port=15237,
        schema="APP",
        server_version="8.1.4.80",
    )

    result = run_explain(
        connection,
        request,
        DmSqlParser().parse(request.sql.text),
        "ignored",
        target=target,
    )

    assert result.metadata.target is target


def test_run_explain_rejects_sql_that_is_empty_after_the_prefix() -> None:
    connection = FakeConnection()
    request = request_for("EXPLAIN")

    with pytest.raises(InvalidArgumentError):
        run_explain(connection, request, DmSqlParser().parse(request.sql.text), "test")

    assert connection.explained == []
    assert connection.cursor_calls == 0


def test_run_explain_reports_a_partial_parse_from_the_plan_body() -> None:
    connection = FakeConnection(f"{SIMPLE_PLAN}\ngarbage")
    request = request_for("SELECT 1 AS N FROM DUAL")

    result = run_explain(connection, request, DmSqlParser().parse(request.sql.text), "test")

    assert result.parse_status is PlanParseStatus.PARTIAL
    assert result.parse_warning == "line 3 could not be parsed"
    assert len(result.nodes) == 2
