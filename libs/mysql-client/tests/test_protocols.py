from __future__ import annotations

from typing import TYPE_CHECKING

from mysql_client.enums import CancellationReason, ExplainFormat

if TYPE_CHECKING:
    from mysql_client.protocols import CancellationController, QuerySession
    from mysql_client.request_models import (
        BenchmarkRequest,
        CompareRequest,
        ExplainRequest,
        InspectionRequest,
        ReadRequest,
        WriteRequest,
    )
    from mysql_client.result_models import (
        BenchmarkResult,
        CompareResult,
        ExplainResult,
        InspectionResult,
        QueryResult,
        WriteResult,
    )


class FakeQuerySession:
    async def execute_read(self, request: ReadRequest) -> QueryResult:
        del request
        raise NotImplementedError

    async def execute_write(self, request: WriteRequest) -> WriteResult:
        del request
        raise NotImplementedError

    async def execute_explain(self, request: ExplainRequest) -> ExplainResult:
        del request
        raise NotImplementedError

    async def execute_benchmark(self, request: BenchmarkRequest) -> BenchmarkResult:
        del request
        raise NotImplementedError

    async def execute_compare(self, request: CompareRequest) -> CompareResult:
        del request
        raise NotImplementedError

    async def execute_inspection(self, request: InspectionRequest) -> InspectionResult:
        del request
        raise NotImplementedError


class FakeCancellationController:
    is_cancelled = False

    async def cancel(self, reason: CancellationReason = CancellationReason.USER_REQUEST) -> None:
        del reason

    async def raise_if_cancelled(self) -> None:
        return None


def test_query_session_protocol_is_async_and_strongly_typed() -> None:
    session: QuerySession = FakeQuerySession()
    controller: CancellationController = FakeCancellationController()

    assert session is not None
    assert controller.is_cancelled is False
    assert ExplainFormat.JSON.value == "json"
