"""Server and schema inspection and maintenance Click commands."""

from __future__ import annotations

from typing import TYPE_CHECKING

import click

from mysql_cli.domain.command import CommandAction, CommandGroup, CommandRequest, DiagnosticErrorType
from mysql_cli.presentation.click.failures import argument_failure
from mysql_cli.presentation.click.runtime import execute
from mysql_cli.presentation.click.types import DATABASE_NAME, POSITIVE_FLOAT, TABLE_NAME

if TYPE_CHECKING:
    from mysql_client import DatabaseName, TableName


@click.group()
def server() -> None:
    """Inspect the selected server."""


@server.command("inspect")
@click.pass_context
def server_inspect(ctx: click.Context) -> None:
    """Inspect server identity and connection details."""

    execute(ctx, CommandRequest(group=CommandGroup.SERVER, action=CommandAction.INSPECT))


@server.command("capabilities")
@click.pass_context
def server_capabilities(ctx: click.Context) -> None:
    """Inspect server capabilities."""

    execute(ctx, CommandRequest(group=CommandGroup.SERVER, action=CommandAction.CAPABILITIES))


@server.command("variables")
@click.option("--filter", "filter_text", help="case-insensitive substring of the variable name")
@click.option("--all", "include_all", is_flag=True, help="include all server variables")
@click.pass_context
def server_variables(ctx: click.Context, filter_text: str | None, include_all: bool) -> None:
    """List read-only server variable facts."""

    _execute_server_metrics(
        ctx,
        action=CommandAction.VARIABLES,
        filter_text=filter_text,
        include_all=include_all,
    )


@server.command("status")
@click.option("--filter", "filter_text", help="case-insensitive substring of the status name")
@click.option("--all", "include_all", is_flag=True, help="include all server status metrics")
@click.pass_context
def server_status(ctx: click.Context, filter_text: str | None, include_all: bool) -> None:
    """List read-only server status facts."""

    _execute_server_metrics(
        ctx,
        action=CommandAction.STATUS,
        filter_text=filter_text,
        include_all=include_all,
    )


@server.command("processes")
@click.option(
    "--include-sql",
    "include_sql",
    is_flag=True,
    help="include process INFO SQL text; it may contain sensitive SQL or credentials",
)
@click.pass_context
def server_processes(ctx: click.Context, include_sql: bool) -> None:
    """List read-only process and thread facts.

    SQL text is omitted by default. --include-sql adds the INFO text, which may
    contain sensitive SQL or credentials. Visibility follows MySQL PROCESS
    privileges: without them the server may return only the current user's
    threads, and privileges are never escalated.
    """

    execute(
        ctx,
        CommandRequest(
            group=CommandGroup.SERVER,
            action=CommandAction.PROCESSES,
            server_include_sql=include_sql,
        ),
    )


def _execute_server_metrics(
    ctx: click.Context,
    *,
    action: CommandAction,
    filter_text: str | None,
    include_all: bool,
) -> None:
    normalized_filter = _validated_metric_filter(filter_text, include_all)
    execute(
        ctx,
        CommandRequest(
            group=CommandGroup.SERVER,
            action=action,
            server_filter_text=normalized_filter,
            server_all=include_all,
        ),
    )


def _validated_metric_filter(filter_text: str | None, include_all: bool) -> str | None:
    if filter_text is not None and include_all:
        raise argument_failure(
            "--filter and --all cannot be used together",
            "--filter/--all",
            error_type=DiagnosticErrorType.MUTUALLY_EXCLUSIVE_INPUTS,
        )
    if filter_text is None:
        return None
    normalized = filter_text.strip()
    if not normalized:
        raise argument_failure("--filter must not be empty", "--filter")
    return normalized


@click.group()
def schema() -> None:
    """Inspect databases, tables, indexes and statistics."""


@schema.command("databases")
@click.pass_context
def schema_databases(ctx: click.Context) -> None:
    """List databases."""

    execute(ctx, CommandRequest(group=CommandGroup.SCHEMA, action=CommandAction.DATABASES))


@schema.command("tables")
@click.option("--database", type=DATABASE_NAME)
@click.pass_context
def schema_tables(ctx: click.Context, database: DatabaseName | None) -> None:
    """List tables in a database."""

    execute(ctx, CommandRequest(group=CommandGroup.SCHEMA, action=CommandAction.TABLES, schema_database=database))


@schema.command("describe")
@click.option("--database", type=DATABASE_NAME)
@click.option("--table", type=TABLE_NAME, required=True)
@click.pass_context
def schema_describe(ctx: click.Context, database: DatabaseName | None, table: TableName) -> None:
    """Describe one table."""

    execute(
        ctx,
        CommandRequest(
            group=CommandGroup.SCHEMA,
            action=CommandAction.DESCRIBE,
            schema_database=database,
            schema_table=table,
        ),
    )


@schema.command("indexes")
@click.option("--database", type=DATABASE_NAME)
@click.option("--table", type=TABLE_NAME, required=True)
@click.pass_context
def schema_indexes(ctx: click.Context, database: DatabaseName | None, table: TableName) -> None:
    """List indexes for one table."""

    execute(
        ctx,
        CommandRequest(
            group=CommandGroup.SCHEMA,
            action=CommandAction.INDEXES,
            schema_database=database,
            schema_table=table,
        ),
    )


@schema.command("stats")
@click.option("--database", type=DATABASE_NAME)
@click.option("--table", type=TABLE_NAME)
@click.pass_context
def schema_stats(ctx: click.Context, database: DatabaseName | None, table: TableName | None) -> None:
    """Inspect schema or table statistics."""

    execute(
        ctx,
        CommandRequest(
            group=CommandGroup.SCHEMA,
            action=CommandAction.STATS,
            schema_database=database,
            schema_table=table,
        ),
    )


@schema.command("analyze")
@click.option("--table", type=TABLE_NAME, required=True)
@click.option("--database", type=DATABASE_NAME)
@click.option("--timeout", "timeout_seconds", type=POSITIVE_FLOAT, help="statement timeout in seconds")
@click.pass_context
def schema_analyze(
    ctx: click.Context,
    database: DatabaseName | None,
    table: TableName,
    timeout_seconds: float | None,
) -> None:
    """Execute ANALYZE TABLE for one table.

    It is not a read-only query and may take metadata locks.
    """

    execute(
        ctx,
        CommandRequest(
            group=CommandGroup.SCHEMA,
            action=CommandAction.ANALYZE,
            schema_database=database,
            schema_table=table,
            schema_timeout_seconds=timeout_seconds,
        ),
    )


__all__ = ["schema", "server"]
