"""Command groups registered by the Click root."""

from mysql_cli.presentation.click.commands.inspection import schema, server
from mysql_cli.presentation.click.commands.profile import profile
from mysql_cli.presentation.click.commands.sql import sql

__all__ = ["profile", "schema", "server", "sql"]
