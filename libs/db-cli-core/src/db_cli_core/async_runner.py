"""Synchronous ownership wrapper for one persistent asyncio event loop."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from collections.abc import Awaitable

ResultType = TypeVar("ResultType")


class AsyncRunner:
    """Run async database drivers safely on one loop for the process lifetime."""

    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()

    def run(self, operation: Awaitable[ResultType]) -> ResultType:
        if self._loop.is_closed():
            raise RuntimeError("异步运行时已关闭")
        return self._loop.run_until_complete(operation)

    def close(self) -> None:
        if not self._loop.is_closed():
            self._loop.close()
