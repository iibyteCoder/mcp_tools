"""Cooperative cancellation primitives used by a session."""

from __future__ import annotations

import asyncio

from mysql_client.enums import CancellationReason
from mysql_client.errors import QueryCancelledError


class CancellationToken:
    """An explicit cancellation controller that can wake a running session."""

    def __init__(self) -> None:
        self._event = asyncio.Event()
        self._reason = CancellationReason.USER_REQUEST

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    @property
    def reason(self) -> CancellationReason:
        return self._reason

    async def cancel(self, reason: CancellationReason = CancellationReason.USER_REQUEST) -> None:
        self._reason = reason
        self._event.set()

    async def raise_if_cancelled(self) -> None:
        if self.is_cancelled:
            raise QueryCancelledError(f"查询已取消 (原因: {self._reason.value})")

    async def wait(self) -> CancellationReason:
        await self._event.wait()
        return self._reason
