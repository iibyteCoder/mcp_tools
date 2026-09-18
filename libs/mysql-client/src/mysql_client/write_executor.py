"""One-statement transaction execution."""

from __future__ import annotations

from typing import TYPE_CHECKING

from mysql_client.enums import TransactionAction, WriteOutcome
from mysql_client.errors import WriteExecutionError
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
        try:
            await connection.begin()
        except BaseException as exc:
            raise WriteExecutionError("写入事务未能开始", outcome=WriteOutcome.DETERMINED_FAILURE) from exc

        try:
            async with connection.cursor() as cursor:
                await cursor.execute(str(request.sql.text), request.parameters)
                affected_rows = max(cursor.rowcount, 0)
                generated_values = () if cursor.lastrowid is None else (cursor.lastrowid,)
        except BaseException as exc:
            rollback_succeeded = await self._try_rollback(connection)
            outcome = WriteOutcome.ROLLED_BACK if rollback_succeeded else WriteOutcome.UNKNOWN
            raise WriteExecutionError("写入执行失败", outcome=outcome) from exc

        try:
            if request.transaction is TransactionAction.COMMIT:
                await connection.commit()
                outcome = WriteOutcome.COMMITTED
            else:
                await connection.rollback()
                outcome = WriteOutcome.ROLLED_BACK
        except BaseException as exc:
            raise WriteExecutionError("写入事务最终状态未知", outcome=WriteOutcome.UNKNOWN) from exc

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
            outcome=outcome,
        )

    @staticmethod
    async def _try_rollback(connection: DriverConnection) -> bool:
        try:
            await connection.rollback()
        except BaseException:
            return False
        return True
