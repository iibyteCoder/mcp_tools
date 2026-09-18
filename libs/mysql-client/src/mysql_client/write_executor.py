"""One-statement transaction execution."""

from __future__ import annotations

from contextlib import suppress
from typing import TYPE_CHECKING

from mysql_client.enums import TransactionAction
from mysql_client.result_models import ExecutionMetadata, WriteResult

if TYPE_CHECKING:
    from mysql_client.driver_adapter import DriverConnection
    from mysql_client.request_models import WriteRequest


class WriteExecutor:
    """Execute exactly one write and make its transaction decision explicit."""

    async def execute(
        self,
        connection: DriverConnection,
        request: WriteRequest,
        *,
        metadata: ExecutionMetadata,
    ) -> WriteResult:
        await connection.begin()
        try:
            async with connection.cursor() as cursor:
                await cursor.execute(str(request.sql.text), request.parameters)
                affected_rows = max(cursor.rowcount, 0)
                generated_values = () if cursor.lastrowid is None else (cursor.lastrowid,)
            if request.transaction is TransactionAction.COMMIT:
                await connection.commit()
            else:
                await connection.rollback()
        except BaseException:
            with suppress(BaseException):
                await connection.rollback()
            raise
        result_metadata = ExecutionMetadata(
            statement_type=request.statement_type,
            duration_ms=metadata.duration_ms,
            affected_rows=affected_rows,
            target=metadata.target,
            started_at=metadata.started_at,
        )
        return WriteResult(
            affected_rows=affected_rows,
            metadata=result_metadata,
            generated_values=generated_values,
        )
