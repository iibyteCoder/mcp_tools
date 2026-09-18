"""Seam implemented by Redis and MySQL adapters."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from db_cli_core.types import Arguments
    from mcp_base.types import ToolResult


class DatabaseBackend(Protocol):
    @property
    def connection_info(self) -> dict[str, Any]:
        """Return the active, secret-safe connection configuration."""

    @property
    def target_label(self) -> str:
        """Return the active database label displayed by the REPL."""

    def invoke(self, tool_name: str, arguments: Arguments) -> ToolResult:
        """Invoke one database operation and return its structured result."""

    def switch_target(self, target: str) -> ToolResult:
        """Switch the active database and establish the new connection."""

    def configure(self, **overrides: Any) -> None:
        """Apply connection settings without opening a connection."""

    def build_profile(self, **overrides: Any) -> dict[str, Any]:
        """Build a complete, persistable connection profile."""

    def reset_configuration(self) -> None:
        """Restore the process baseline derived from environment settings."""

    def close(self) -> None:
        """Release all database and event-loop resources."""
