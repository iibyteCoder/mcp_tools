"""Schema inspection Click commands."""

from __future__ import annotations

from typing import TYPE_CHECKING

import click

from dm_cli.domain.command import CommandAction, CommandGroup, CommandRequest, DiagnosticErrorType
from dm_cli.presentation.click.failures import argument_failure
from dm_cli.presentation.click.runtime import execute, selected_profile
from dm_cli.presentation.click.types import (
    OBJECT_NAME,
    OBJECT_TYPE,
    PERCENTAGE,
    POSITIVE_INTEGER,
    SCHEMA_NAME,
    TABLE_NAME,
    object_type,
)
from dm_client.domain.enums import ObjectType

if TYPE_CHECKING:
    from dm_client.domain.values import ObjectName, SchemaName, TableName


@click.group()
def schema() -> None:
    """Inspect DM schemas, tables and columns."""


@schema.command("databases")
@click.option("--all", "schema_all", is_flag=True, help="include system schemas")
@click.pass_context
def schema_databases(ctx: click.Context, schema_all: bool) -> None:
    """List schemas visible to the connected user."""

    execute(
        ctx,
        CommandRequest(
            group=CommandGroup.SCHEMA,
            action=CommandAction.DATABASES,
            selected_profile=selected_profile(ctx),
            schema_all=schema_all,
        ),
    )


@schema.command("tables")
@click.option("--schema", "schema_name", type=SCHEMA_NAME, help="schema name")
@click.option("--database", "database_name", type=SCHEMA_NAME, help="alias for --schema")
@click.pass_context
def schema_tables(
    ctx: click.Context,
    schema_name: SchemaName | None,
    database_name: SchemaName | None,
) -> None:
    """List tables in the selected or named schema."""

    execute(
        ctx,
        CommandRequest(
            group=CommandGroup.SCHEMA,
            action=CommandAction.TABLES,
            selected_profile=selected_profile(ctx),
            schema_name=_selected_schema(schema_name, database_name),
        ),
    )


@schema.command("describe")
@click.option("--table", "table_name", type=TABLE_NAME, required=True, help="table name")
@click.option("--schema", "schema_name", type=SCHEMA_NAME, help="schema name")
@click.option("--database", "database_name", type=SCHEMA_NAME, help="alias for --schema")
@click.pass_context
def schema_describe(
    ctx: click.Context,
    table_name: TableName,
    schema_name: SchemaName | None,
    database_name: SchemaName | None,
) -> None:
    """Describe the columns and comments of one table."""

    execute(
        ctx,
        CommandRequest(
            group=CommandGroup.SCHEMA,
            action=CommandAction.DESCRIBE,
            selected_profile=selected_profile(ctx),
            schema_name=_selected_schema(schema_name, database_name),
            schema_table=table_name,
        ),
    )


@schema.command("indexes")
@click.option("--table", "table_name", type=TABLE_NAME, required=True, help="table name")
@click.option("--schema", "schema_name", type=SCHEMA_NAME, help="schema name")
@click.option("--database", "database_name", type=SCHEMA_NAME, help="alias for --schema")
@click.pass_context
def schema_indexes(
    ctx: click.Context,
    table_name: TableName,
    schema_name: SchemaName | None,
    database_name: SchemaName | None,
) -> None:
    """List the indexes and index columns of one table."""

    execute(
        ctx,
        CommandRequest(
            group=CommandGroup.SCHEMA,
            action=CommandAction.INDEXES,
            selected_profile=selected_profile(ctx),
            schema_name=_selected_schema(schema_name, database_name),
            schema_table=table_name,
        ),
    )


@schema.command("stats")
@click.option("--table", "table_name", type=TABLE_NAME, help="table name")
@click.option("--schema", "schema_name", type=SCHEMA_NAME, help="schema name")
@click.option("--database", "database_name", type=SCHEMA_NAME, help="alias for --schema")
@click.pass_context
def schema_stats(
    ctx: click.Context,
    table_name: TableName | None,
    schema_name: SchemaName | None,
    database_name: SchemaName | None,
) -> None:
    """Show table statistics for the selected or named schema."""

    execute(
        ctx,
        CommandRequest(
            group=CommandGroup.SCHEMA,
            action=CommandAction.STATS,
            selected_profile=selected_profile(ctx),
            schema_name=_selected_schema(schema_name, database_name),
            schema_table=table_name,
        ),
    )


def _selected_schema(
    schema_name: SchemaName | None,
    database_name: SchemaName | None,
) -> SchemaName | None:
    if schema_name is not None and database_name is not None:
        raise argument_failure(
            "--schema and --database are aliases and cannot be used together",
            "--schema/--database",
            error_type=DiagnosticErrorType.MUTUALLY_EXCLUSIVE_INPUTS,
        )
    return schema_name if schema_name is not None else database_name


@schema.command("ddl")
@click.option(
    "--type",
    "type_value",
    type=OBJECT_TYPE,
    default=ObjectType.TABLE.value,
    show_default=True,
    help="object type",
)
@click.option("--name", "object_name", type=OBJECT_NAME, required=True, help="object name")
@click.option("--schema", "schema_name", type=SCHEMA_NAME, help="schema name")
@click.option("--database", "database_name", type=SCHEMA_NAME, help="alias for --schema")
@click.pass_context
def schema_ddl(
    ctx: click.Context,
    type_value: str,
    object_name: ObjectName,
    schema_name: SchemaName | None,
    database_name: SchemaName | None,
) -> None:
    """Show the DM-generated DDL of one catalog object."""

    execute(
        ctx,
        CommandRequest(
            group=CommandGroup.SCHEMA,
            action=CommandAction.DDL,
            selected_profile=selected_profile(ctx),
            schema_name=_selected_schema(schema_name, database_name),
            schema_object_type=object_type(type_value),
            schema_object_name=object_name,
        ),
    )


@schema.command("constraints")
@click.option("--table", "table_name", type=TABLE_NAME, help="table name")
@click.option("--schema", "schema_name", type=SCHEMA_NAME, help="schema name")
@click.option("--database", "database_name", type=SCHEMA_NAME, help="alias for --schema")
@click.pass_context
def schema_constraints(
    ctx: click.Context,
    table_name: TableName | None,
    schema_name: SchemaName | None,
    database_name: SchemaName | None,
) -> None:
    """List constraints of the selected schema or one table."""

    execute(
        ctx,
        CommandRequest(
            group=CommandGroup.SCHEMA,
            action=CommandAction.CONSTRAINTS,
            selected_profile=selected_profile(ctx),
            schema_name=_selected_schema(schema_name, database_name),
            schema_table=table_name,
        ),
    )


@schema.command("objects")
@click.option("--type", "type_value", type=OBJECT_TYPE, help="object type")
@click.option("--schema", "schema_name", type=SCHEMA_NAME, help="schema name")
@click.option("--database", "database_name", type=SCHEMA_NAME, help="alias for --schema")
@click.pass_context
def schema_objects(
    ctx: click.Context,
    type_value: str | None,
    schema_name: SchemaName | None,
    database_name: SchemaName | None,
) -> None:
    """List catalog objects of the selected schema."""

    execute(
        ctx,
        CommandRequest(
            group=CommandGroup.SCHEMA,
            action=CommandAction.OBJECTS,
            selected_profile=selected_profile(ctx),
            schema_name=_selected_schema(schema_name, database_name),
            schema_object_type=None if type_value is None else object_type(type_value),
        ),
    )


@schema.command("analyze")
@click.option("--table", "table_name", type=TABLE_NAME, required=True, help="table name")
@click.option("--schema", "schema_name", type=SCHEMA_NAME, help="schema name")
@click.option("--database", "database_name", type=SCHEMA_NAME, help="alias for --schema")
@click.option("--partition", "partition_name", help="partition name")
@click.option(
    "--estimate-percent",
    "estimate_percent",
    type=PERCENTAGE,
    help="sampled row percentage; greater than 0 and at most 100",
)
@click.option(
    "--cascade/--no-cascade",
    "cascade",
    default=True,
    show_default=True,
    help="analyze dependent indexes",
)
@click.option("--degree", "degree", type=POSITIVE_INTEGER, help="parallel degree")
@click.pass_context
def schema_analyze(
    ctx: click.Context,
    table_name: TableName,
    schema_name: SchemaName | None,
    database_name: SchemaName | None,
    partition_name: str | None,
    estimate_percent: float | None,
    cascade: bool,
    degree: int | None,
) -> None:
    """Collect table statistics with DBMS_STATS; the call auto-commits."""

    execute(
        ctx,
        CommandRequest(
            group=CommandGroup.SCHEMA,
            action=CommandAction.ANALYZE,
            selected_profile=selected_profile(ctx),
            schema_name=_selected_schema(schema_name, database_name),
            schema_table=table_name,
            schema_partition=partition_name,
            schema_estimate_percent=estimate_percent,
            schema_cascade=cascade,
            schema_degree=degree,
        ),
    )


__all__ = ["schema"]
