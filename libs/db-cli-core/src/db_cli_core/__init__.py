"""Shared framework for database command-line clients."""

from db_cli_core.catalog import CommandCatalog, CommandDescriptor
from db_cli_core.context import CommandContext
from db_cli_core.contracts import DatabaseBackend
from db_cli_core.profile_commands import register_profile_commands
from db_cli_core.registration import register_catalog

__all__ = [
    "CommandCatalog",
    "CommandContext",
    "CommandDescriptor",
    "DatabaseBackend",
    "register_catalog",
    "register_profile_commands",
]
