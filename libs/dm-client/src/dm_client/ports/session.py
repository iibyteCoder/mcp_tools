"""Dependency-free asynchronous protocols for DM execution adapters."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from dm_client.domain.requests import (
        BenchmarkRequest,
        CatalogRequest,
        CompareRequest,
        ExplainRequest,
        InspectionRequest,
        MaintenanceRequest,
        ReadRequest,
        WriteRequest,
    )
    from dm_client.domain.results import (
        AnalyzeResult,
        BenchmarkResult,
        CompareResult,
        DdlResult,
        ExplainResult,
        InspectionResponse,
        QueryResult,
        WriteResult,
    )


class QuerySession(Protocol):
    """Execute typed requests against one already-selected DM target asynchronously."""

    async def execute_read(self, request: ReadRequest) -> QueryResult:
        """Return a bounded tabular result with execution metadata."""

    async def execute_write(self, request: WriteRequest) -> WriteResult:
        """Execute one write request and return its typed result."""

    async def execute_explain(self, request: ExplainRequest) -> ExplainResult:
        """Return the text execution plan without executing the SQL."""

    async def execute_benchmark(self, request: BenchmarkRequest) -> BenchmarkResult:
        """Execute one benchmark request and return its typed timings."""

    async def execute_compare(self, request: CompareRequest) -> CompareResult:
        """Execute one comparison request and return its typed result."""

    async def execute_inspection(self, request: InspectionRequest) -> InspectionResponse:
        """Execute one trusted, read-only server or schema inspection."""

    async def execute_catalog(self, request: CatalogRequest) -> DdlResult:
        """Return generated DDL for one catalog object."""

    async def execute_maintenance(self, request: MaintenanceRequest) -> AnalyzeResult:
        """Execute one table-level statistics maintenance request."""


__all__ = ["QuerySession"]
