"""Single-thread executor for synchronous driver calls."""

from __future__ import annotations

import asyncio
import functools
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Final, ParamSpec, TypeVar

if TYPE_CHECKING:
    from collections.abc import Callable

EXECUTOR_THREAD_NAME_PREFIX: Final[str] = "db-dm"

_P = ParamSpec("_P")
_R = TypeVar("_R")


class DriverExecutor:
    """Run every call for one connection on one dedicated worker thread."""

    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix=EXECUTOR_THREAD_NAME_PREFIX,
        )
        self._closed = False

    async def run(self, func: Callable[_P, _R], *args: _P.args, **kwargs: _P.kwargs) -> _R:
        """Run one synchronous driver call without blocking the event loop."""

        if self._closed:
            raise RuntimeError("driver executor is already shut down")
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, functools.partial(func, *args, **kwargs))

    def shutdown(self) -> None:
        """Stop accepting work and wait for the worker thread to finish."""

        if self._closed:
            return
        self._closed = True
        self._executor.shutdown(wait=True)


__all__ = ["EXECUTOR_THREAD_NAME_PREFIX", "DriverExecutor"]
