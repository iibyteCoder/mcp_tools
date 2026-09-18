"""Dependency-free asynchronous protocols for execution adapters."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from mysql_client.enums import CancellationReason

if TYPE_CHECKING:
    from mysql_client.request_models import (
        BenchmarkRequest,
        CompareRequest,
        ExplainRequest,
        ParsedSql,
        ReadRequest,
        SqlInput,
        WriteRequest,
    )
    from mysql_client.result_models import (
        BenchmarkResult,
        CompareResult,
        ExplainResult,
        QueryResult,
        WriteResult,
    )
    from mysql_client.value_models import SqlText


class SqlParser(Protocol):
    """Parse SQL without depending on a driver or CLI framework."""

    def parse(self, sql: SqlInput | SqlText) -> ParsedSql:
        """Return the normalized SQL and its statement family."""


class QuerySession(Protocol):
    """Execute typed requests against one already-selected target asynchronously."""

    async def execute_read(self, request: ReadRequest) -> QueryResult:
        """Return a bounded tabular result with columns and execution metadata."""

    async def execute_write(self, request: WriteRequest) -> WriteResult:
        """Execute one write request and return its typed result."""

    async def execute_explain(self, request: ExplainRequest) -> ExplainResult:
        """Execute one explain request and return its typed result."""

    async def execute_benchmark(self, request: BenchmarkRequest) -> BenchmarkResult:
        """Execute one benchmark request and return its typed result."""

    async def execute_compare(self, request: CompareRequest) -> CompareResult:
        """Execute one comparison request and return its typed result."""


class CancellationController(Protocol):
    """Cooperative cancellation seam; policy and implementation come later."""

    @property
    def is_cancelled(self) -> bool:
        """Whether cancellation has been requested."""

    async def cancel(self, reason: CancellationReason = CancellationReason.USER_REQUEST) -> None:
        """Request asynchronous cancellation of the current operation."""

    async def raise_if_cancelled(self) -> None:
        """Raise the session's cancellation error when cancellation is observed."""
