"""Server and schema inspection Click commands."""

from __future__ import annotations

from typing import TYPE_CHECKING

import click

from mysql_cli.domain.command import CommandAction, CommandGroup, CommandRequest
from mysql_cli.presentation.click.runtime import execute
from mysql_cli.presentation.click.types import DATABASE_NAME, TABLE_NAME

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


__all__ = ["schema", "server"]
