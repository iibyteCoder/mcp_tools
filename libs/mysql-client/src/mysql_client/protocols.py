"""Minimal dependency-free protocols for parser and execution adapters."""

from __future__ import annotations

from typing import Protocol

from mysql_client.models import (
    CancellationReason,
    ParsedSql,
    Request,
    ResponsePayload,
    SqlInput,
)


class SqlParser(Protocol):
    """Parse SQL without depending on a driver or CLI framework."""

    def parse(self, sql: SqlInput) -> ParsedSql:
        """Return the normalized SQL and its statement family."""


class QuerySession(Protocol):
    """Execute typed requests against one already-selected target."""

    def execute(self, request: Request) -> ResponsePayload:
        """Execute one request and return a typed result."""


class CancellationController(Protocol):
    """Cooperative cancellation seam; policy and implementation come later."""

    @property
    def is_cancelled(self) -> bool:
        """Whether cancellation has been requested."""

    def cancel(self, reason: CancellationReason = CancellationReason.USER_REQUEST) -> None:
        """Request cancellation of the current operation."""

    def raise_if_cancelled(self) -> None:
        """Raise the session's cancellation error when cancellation is observed."""
