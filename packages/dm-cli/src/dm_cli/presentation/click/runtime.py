"""Shared request assembly and execution for the Click command groups."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from dm_cli.application.input import SQL_INPUT_ARGUMENT
from dm_cli.application.runner import (
    CliRuntime,
    CommandData,
    execute_request,
    request_requires_stdin,
)
from dm_cli.domain.command import CommandAction, CommandGroup, CommandRequest, DiagnosticErrorType, SqlInputSpec
from dm_cli.presentation.click.failures import argument_failure
from dm_cli.presentation.click.rendering import write_success
from dm_client.domain.enums import TransactionAction

if TYPE_CHECKING:
    import click

    from dm_cli.domain.profile import ProfileName


def runtime(ctx: click.Context) -> CliRuntime:
    value = ctx.ensure_object(CliRuntime)
    if not isinstance(value, CliRuntime):
        raise TypeError("Click context object must be CliRuntime")
    return value


def selected_profile(ctx: click.Context) -> ProfileName | None:
    return runtime(ctx).selected_profile


def execute(ctx: click.Context, request: CommandRequest) -> None:
    current_runtime = runtime(ctx)
    stdin_text = sys.stdin.read() if request_requires_stdin(request) else None
    data: CommandData = asyncio.run(execute_request(current_runtime, request, stdin_text=stdin_text))
    resolved_request = current_runtime.request
    if resolved_request is None:
        raise RuntimeError("command runner did not retain the request")
    write_success(data, resolved_request)


def sql_request(
    action: CommandAction,
    *,
    selected: ProfileName | None,
    sql_text: str | None,
    sql_file: Path | None,
    params_file: Path | None,
    max_rows: int | None = None,
    max_bytes: int | None = None,
    iterations: int | None = None,
    warmup_iterations: int | None = None,
    actual: bool = False,
    transaction: TransactionAction = TransactionAction.COMMIT,
    timeout_seconds: float | None = None,
) -> CommandRequest:
    """Build one validated SQL command request from Click option values."""

    return CommandRequest(
        group=CommandGroup.SQL,
        action=action,
        selected_profile=selected,
        sql_input=sql_spec(sql_text, sql_file),
        params_file=params_file,
        sql_max_rows=max_rows,
        sql_max_bytes=max_bytes,
        sql_iterations=iterations,
        sql_warmup_iterations=warmup_iterations,
        sql_explain_actual=actual,
        sql_transaction=transaction,
        sql_timeout_seconds=timeout_seconds,
    )


def sql_spec(
    sql_text: str | None,
    sql_file: Path | None,
    *,
    argument: str = SQL_INPUT_ARGUMENT,
    allow_stdin: bool = True,
) -> SqlInputSpec:
    """Resolve the mutually exclusive inline or file SQL input."""

    if sql_text is not None and sql_file is not None:
        raise argument_failure(
            f"use only one of {argument}",
            argument,
            error_type=DiagnosticErrorType.MUTUALLY_EXCLUSIVE_INPUTS,
        )
    if sql_text is not None:
        return SqlInputSpec.inline(sql_text)
    if sql_file is None:
        raise argument_failure(
            f"one of {argument} is required",
            argument,
            error_type=DiagnosticErrorType.MISSING_SQL,
        )
    if sql_file == Path("-"):
        if not allow_stdin:
            raise argument_failure(
                f"{argument} does not support standard input",
                argument,
            )
        return SqlInputSpec.stdin()
    return SqlInputSpec.file(sql_file)


__all__ = ["execute", "runtime", "selected_profile", "sql_request", "sql_spec"]
