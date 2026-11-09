"""SQL read, write, explain, benchmark and compare Click commands."""

from __future__ import annotations

from typing import TYPE_CHECKING

import click

from dm_cli.application.input import COMPARE_LEFT_SQL_ARGUMENT, COMPARE_RIGHT_SQL_ARGUMENT
from dm_cli.domain.command import CommandAction, CommandGroup, CommandRequest
from dm_cli.presentation.click.runtime import execute, selected_profile, sql_request, sql_spec
from dm_cli.presentation.click.types import (
    NON_NEGATIVE_INTEGER,
    PATH,
    POSITIVE_FLOAT,
    POSITIVE_INTEGER,
    SQL_PATH,
    TRANSACTION,
)
from dm_client.domain.enums import TransactionAction

if TYPE_CHECKING:
    from pathlib import Path


@click.group()
def sql() -> None:
    """Parse or execute one SQL statement."""


@sql.command("read")
@click.option("--sql", "sql_text", type=str, help="inline SQL text")
@click.option("--sql-file", "sql_file", type=SQL_PATH, help="SQL file path; - reads stdin")
@click.option("--params-file", type=PATH)
@click.option("--max-rows", type=POSITIVE_INTEGER)
@click.option("--max-bytes", type=POSITIVE_INTEGER)
@click.option("--timeout", "timeout_seconds", type=POSITIVE_FLOAT)
@click.pass_context
def sql_read(
    ctx: click.Context,
    sql_text: str | None,
    sql_file: Path | None,
    params_file: Path | None,
    max_rows: int | None,
    max_bytes: int | None,
    timeout_seconds: float | None,
) -> None:
    """Read rows from one SQL statement."""

    execute(
        ctx,
        sql_request(
            CommandAction.READ,
            selected=selected_profile(ctx),
            sql_text=sql_text,
            sql_file=sql_file,
            params_file=params_file,
            max_rows=max_rows,
            max_bytes=max_bytes,
            timeout_seconds=timeout_seconds,
        ),
    )


@sql.command("write")
@click.option("--sql", "sql_text", type=str, help="inline SQL text")
@click.option("--sql-file", "sql_file", type=SQL_PATH, help="SQL file path; - reads stdin")
@click.option("--params-file", type=PATH)
@click.option("--transaction", type=TRANSACTION, default=TransactionAction.COMMIT.value, show_default=True)
@click.option("--timeout", "timeout_seconds", type=POSITIVE_FLOAT)
@click.pass_context
def sql_write(
    ctx: click.Context,
    sql_text: str | None,
    sql_file: Path | None,
    params_file: Path | None,
    transaction: str,
    timeout_seconds: float | None,
) -> None:
    """Execute one authorized mutation or DDL statement."""

    execute(
        ctx,
        sql_request(
            CommandAction.WRITE,
            selected=selected_profile(ctx),
            sql_text=sql_text,
            sql_file=sql_file,
            params_file=params_file,
            transaction=TransactionAction(transaction),
            timeout_seconds=timeout_seconds,
        ),
    )


@sql.command("explain")
@click.option("--sql", "sql_text", type=str, help="inline SQL text")
@click.option("--sql-file", "sql_file", type=SQL_PATH, help="SQL file path; - reads stdin")
@click.option(
    "--actual",
    is_flag=True,
    help="execute read-only SQL via disql AUTOTRACE TRACEONLY",
)
@click.option("--timeout", "timeout_seconds", type=POSITIVE_FLOAT)
@click.pass_context
def sql_explain(
    ctx: click.Context,
    sql_text: str | None,
    sql_file: Path | None,
    actual: bool,
    timeout_seconds: float | None,
) -> None:
    """Return the text execution plan; --actual also executes read-only SQL."""

    execute(
        ctx,
        sql_request(
            CommandAction.EXPLAIN,
            selected=selected_profile(ctx),
            sql_text=sql_text,
            sql_file=sql_file,
            params_file=None,
            actual=actual,
            timeout_seconds=timeout_seconds,
        ),
    )


@sql.command("benchmark")
@click.option("--sql", "sql_text", type=str, help="inline SQL text")
@click.option("--sql-file", "sql_file", type=SQL_PATH, help="SQL file path; - reads stdin")
@click.option("--params-file", type=PATH)
@click.option("--iterations", type=POSITIVE_INTEGER)
@click.option("--warmup-iterations", type=NON_NEGATIVE_INTEGER)
@click.option("--timeout", "timeout_seconds", type=POSITIVE_FLOAT)
@click.pass_context
def sql_benchmark(
    ctx: click.Context,
    sql_text: str | None,
    sql_file: Path | None,
    params_file: Path | None,
    iterations: int | None,
    warmup_iterations: int | None,
    timeout_seconds: float | None,
) -> None:
    """Measure one read-only SQL statement."""

    execute(
        ctx,
        sql_request(
            CommandAction.BENCHMARK,
            selected=selected_profile(ctx),
            sql_text=sql_text,
            sql_file=sql_file,
            params_file=params_file,
            iterations=iterations,
            warmup_iterations=warmup_iterations,
            timeout_seconds=timeout_seconds,
        ),
    )


@sql.command("compare")
@click.option("--left-sql", "left_sql", type=str)
@click.option("--left-sql-file", "left_sql_file", type=SQL_PATH)
@click.option("--right-sql", "right_sql", type=str)
@click.option("--right-sql-file", "right_sql_file", type=SQL_PATH)
@click.option("--left-params-file", type=PATH)
@click.option("--right-params-file", type=PATH)
@click.option("--key-column", "key_columns", multiple=True)
@click.option("--max-diff-samples", type=NON_NEGATIVE_INTEGER)
@click.option("--timeout", "timeout_seconds", type=POSITIVE_FLOAT)
@click.pass_context
def sql_compare(
    ctx: click.Context,
    left_sql: str | None,
    left_sql_file: Path | None,
    right_sql: str | None,
    right_sql_file: Path | None,
    left_params_file: Path | None,
    right_params_file: Path | None,
    key_columns: tuple[str, ...],
    max_diff_samples: int | None,
    timeout_seconds: float | None,
) -> None:
    """Compare the results of two read-only SQL statements."""

    execute(
        ctx,
        CommandRequest(
            group=CommandGroup.SQL,
            action=CommandAction.COMPARE,
            selected_profile=selected_profile(ctx),
            compare_left_sql_input=sql_spec(
                left_sql,
                left_sql_file,
                argument=COMPARE_LEFT_SQL_ARGUMENT,
                allow_stdin=False,
            ),
            compare_right_sql_input=sql_spec(
                right_sql,
                right_sql_file,
                argument=COMPARE_RIGHT_SQL_ARGUMENT,
                allow_stdin=False,
            ),
            compare_left_params_file=left_params_file,
            compare_right_params_file=right_params_file,
            compare_key_columns=key_columns,
            compare_max_diff_samples=max_diff_samples,
            sql_timeout_seconds=timeout_seconds,
        ),
    )


__all__ = ["sql"]
