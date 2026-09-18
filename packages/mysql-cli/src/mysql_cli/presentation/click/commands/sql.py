"""SQL command group and its Click request adapters."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, TypeVar

import click

from mysql_cli.domain.command import CommandAction, CommandGroup, CommandRequest
from mysql_cli.presentation.click.runtime import execute, selected_profile, sql_request, sql_spec
from mysql_cli.presentation.click.types import (
    NON_NEGATIVE_INTEGER,
    PATH,
    POSITIVE_FLOAT,
    POSITIVE_INTEGER,
    SQL_PATH,
    TRANSACTION,
)
from mysql_client import TransactionAction

if TYPE_CHECKING:
    from pathlib import Path

CommandCallback = TypeVar("CommandCallback", bound=Callable[..., object])


@click.group()
def sql() -> None:
    """Parse or execute one SQL statement."""


def _sql_input_options(command: CommandCallback) -> CommandCallback:
    """Add common mutually exclusive SQL input options to one command."""

    command_with_text = click.option("--sql", "sql_text", type=str, help="inline SQL text")(command)
    command_with_file = click.option(
        "--sql-file", "sql_file", type=SQL_PATH, help="SQL file path; - reads stdin"
    )(command_with_text)
    return command_with_file


@sql.command("read")
@_sql_input_options
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
@_sql_input_options
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
@_sql_input_options
@click.option("--params-file", type=PATH)
@click.option("--timeout", "timeout_seconds", type=POSITIVE_FLOAT)
@click.pass_context
def sql_explain(
    ctx: click.Context,
    sql_text: str | None,
    sql_file: Path | None,
    params_file: Path | None,
    timeout_seconds: float | None,
) -> None:
    """Execute one EXPLAIN statement exactly as supplied."""

    execute(
        ctx,
        sql_request(
            CommandAction.EXPLAIN,
            selected=selected_profile(ctx),
            sql_text=sql_text,
            sql_file=sql_file,
            params_file=params_file,
            timeout_seconds=timeout_seconds,
        ),
    )


@sql.command("benchmark")
@_sql_input_options
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
    """Measure one SQL statement."""

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
@click.option("--left-sql", type=str)
@click.option("--left-sql-file", type=SQL_PATH)
@click.option("--right-sql", type=str)
@click.option("--right-sql-file", type=SQL_PATH)
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
    """Compare the results of two SQL statements."""

    execute(
        ctx,
        CommandRequest(
            group=CommandGroup.SQL,
            action=CommandAction.COMPARE,
            selected_profile=selected_profile(ctx),
            compare_left_sql_input=sql_spec(left_sql, left_sql_file, label="left SQL", allow_stdin=False),
            compare_right_sql_input=sql_spec(right_sql, right_sql_file, label="right SQL", allow_stdin=False),
            compare_left_params_file=left_params_file,
            compare_right_params_file=right_params_file,
            compare_key_columns=key_columns,
            compare_max_diff_samples=max_diff_samples,
            sql_timeout_seconds=timeout_seconds,
        ),
    )


__all__ = ["sql"]
