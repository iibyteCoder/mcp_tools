"""Unit tests for the best-effort DM text execution-plan parser."""

from __future__ import annotations

from dm_client.domain.enums import PlanParseStatus
from dm_client.execution.plan import PLAN_INDENT_WIDTH, parse_plan

SIMPLE_PLAN = "\n".join(
    (
        "1   #NSET2: [1, 1, 1]",
        "2     #PRJT2: [1, 1, 1]; exp_num(1)",
        "3       #UNION ALL: [18, 4, 48]",
    )
)
CTE_UNION_PLAN = "\n".join(
    (
        "1   #NSET2: [12, 3, 144]",
        "2     #PRJT2: [12, 3, 144]; exp_num(2), is_atom(FALSE)",
        "3       #UNION ALL: [12, 3, 144]",
        "4         #PRJT2: [6, 1, 48]; exp_num(1)",
        "5           #CSCN2: [6, 1, 48]; INDEX33555456(T_A)",
        "6         #PRJT2: [6, 2, 96]; exp_num(1)",
        "7           #CSCN2: [6, 2, 96]; INDEX33555457(T_B)",
    )
)
MULTI_DIGIT_PLAN = "\n".join(
    (
        "1    #NSET2: [8, 1, 48]",
        "2      #PRJT2: [8, 1, 48]; exp_num(1)",
        "10       #CSCN2: [8, 1, 48]; INDEX33555456(T)",
    )
)


def test_simple_plan_parses_every_node() -> None:
    parsed = parse_plan(f"\n\n{SIMPLE_PLAN}\n\n")

    assert parsed.plan_text == SIMPLE_PLAN
    assert parsed.parse_status is PlanParseStatus.PARSED
    assert parsed.parse_warning is None
    assert [node.line for node in parsed.nodes] == [1, 2, 3]
    assert [node.depth for node in parsed.nodes] == [0, 1, 2]
    assert [node.operation for node in parsed.nodes] == ["NSET2", "PRJT2", "UNION ALL"]
    assert [node.text for node in parsed.nodes] == [
        "#NSET2: [1, 1, 1]",
        "#PRJT2: [1, 1, 1]; exp_num(1)",
        "#UNION ALL: [18, 4, 48]",
    ]
    first = parsed.nodes[0]
    assert first.cost == 1.0
    assert first.estimated_rows == 1
    assert first.estimated_bytes == 1
    assert first.detail is None
    assert parsed.nodes[1].detail == "exp_num(1)"
    assert parsed.nodes[2].cost == 18.0
    assert parsed.nodes[2].estimated_rows == 4
    assert parsed.nodes[2].estimated_bytes == 48


def test_cte_union_plan_keeps_operator_names_and_details() -> None:
    parsed = parse_plan(CTE_UNION_PLAN)

    assert parsed.parse_status is PlanParseStatus.PARSED
    assert [node.depth for node in parsed.nodes] == [0, 1, 2, 3, 4, 3, 4]
    assert parsed.nodes[2].operation == "UNION ALL"
    assert parsed.nodes[4].operation == "CSCN2"
    assert parsed.nodes[4].detail == "INDEX33555456(T_A)"
    assert parsed.nodes[6].detail == "INDEX33555457(T_B)"


def test_multi_digit_line_numbers_parse_with_relative_depth() -> None:
    parsed = parse_plan(MULTI_DIGIT_PLAN)

    assert parsed.parse_status is PlanParseStatus.PARSED
    assert [node.line for node in parsed.nodes] == [1, 2, 10]
    assert [node.depth for node in parsed.nodes] == [0, 1, 2]


def test_missing_metrics_and_detail_are_tolerated() -> None:
    parsed = parse_plan(
        "\n".join(
            (
                "1   #NSET2",
                "2     #PRJT2:",
                "3       #UNION ALL",
            )
        )
    )

    assert parsed.parse_status is PlanParseStatus.PARSED
    assert [node.operation for node in parsed.nodes] == ["NSET2", "PRJT2", "UNION ALL"]
    for node in parsed.nodes:
        assert node.cost is None
        assert node.estimated_rows is None
        assert node.estimated_bytes is None
        assert node.detail is None


def test_detail_without_metrics_is_kept() -> None:
    parsed = parse_plan("1   #PRJT2: exp_num(1)")

    assert parsed.parse_status is PlanParseStatus.PARSED
    node = parsed.nodes[0]
    assert node.cost is None
    assert node.estimated_rows is None
    assert node.estimated_bytes is None
    assert node.detail == "exp_num(1)"


def test_malformed_line_reports_partial_with_the_first_unmatched_line() -> None:
    parsed = parse_plan(
        "\n".join(
            (
                "1   #NSET2: [1, 1, 1]",
                "not a plan line",
                "3     #PRJT2: [1, 1, 1]",
            )
        )
    )

    assert parsed.parse_status is PlanParseStatus.PARTIAL
    assert parsed.parse_warning == "line 2 could not be parsed"
    assert [node.line for node in parsed.nodes] == [1, 3]
    assert "not a plan line" not in (parsed.parse_warning or "")


def test_malformed_line_with_a_numeric_prefix_names_that_number() -> None:
    parsed = parse_plan(
        "\n".join(
            (
                "1   #NSET2: [1, 1, 1]",
                "2   oops",
            )
        )
    )

    assert parsed.parse_status is PlanParseStatus.PARTIAL
    assert parsed.parse_warning == "line 2 could not be parsed"
    assert [node.line for node in parsed.nodes] == [1]


def test_empty_plan_fails_without_nodes() -> None:
    parsed = parse_plan("  \n\n\t")

    assert parsed.plan_text == ""
    assert parsed.nodes == ()
    assert parsed.parse_status is PlanParseStatus.FAILED
    assert parsed.parse_warning == "plan text is empty"


def test_non_plan_text_fails_without_nodes() -> None:
    parsed = parse_plan("not a plan")

    assert parsed.nodes == ()
    assert parsed.parse_status is PlanParseStatus.FAILED
    assert parsed.parse_warning == "line 1 could not be parsed"


def test_depth_is_relative_to_the_first_hash_and_clamped_to_zero() -> None:
    parsed = parse_plan(
        "\n".join(
            (
                "  1     #NSET2: [1, 1, 1]",
                "  2   #PRJT2: [1, 1, 1]",
                "  3       #UNION ALL: [1, 1, 1]",
            )
        )
    )

    assert PLAN_INDENT_WIDTH == 2
    assert [node.depth for node in parsed.nodes] == [0, 0, 1]
