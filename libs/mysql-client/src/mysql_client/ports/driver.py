"""Driver port used by execution modules and concrete database adapters."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from mysql_client.domain.enums import DriverFailureKind

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager

    from mysql_client.domain.configuration import MySqlConnectionConfig
    from mysql_client.domain.values import DatabaseParameters, DatabaseValue


@dataclass(frozen=True, slots=True)
class DriverColumn:
    """Driver-neutral column metadata after adapter normalization."""

    name: str
    type_name: str
    nullable: bool = True
    default: DatabaseValue | None = None


DriverRow = Sequence[object]


class DriverFailure(Exception):
    """Non-secret failure information exposed by a driver adapter."""

    def __init__(self, kind: DriverFailureKind, *, errno: int | None = None) -> None:
        self.kind = kind
        self.errno = errno
        super().__init__(kind.value)


class DriverCursor(Protocol):
    """The small cursor surface needed by the domain executors."""

    @property
    def description(self) -> Sequence[DriverColumn] | None: ...

    @property
    def rowcount(self) -> int: ...

    @property
    def lastrowid(self) -> int | None: ...

    async def execute(self, sql: str, parameters: DatabaseParameters) -> None: ...

    async def fetchmany(self, size: int) -> Sequence[DriverRow]: ...


class DriverConnection(Protocol):
    """The single-connection surface required by a MySQL session."""

    @property
    def thread_id(self) -> int | None: ...

    def cursor(self) -> AbstractAsyncContextManager[DriverCursor]: ...

    async def begin(self) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...

    async def close(self) -> None: ...


class DriverFactory(Protocol):
    """Create one isolated driver connection."""

    async def connect(self, config: MySqlConnectionConfig) -> DriverConnection: ...


@runtime_checkable
class QueryKiller(Protocol):
    """Optional independent control-connection capability."""

    async def kill_query(self, config: MySqlConnectionConfig, thread_id: int) -> bool: ...


def _errno_from_exception(exc: BaseException) -> int | None:
    raw_errno = getattr(exc, "errno", None)
    if isinstance(raw_errno, int):
        return raw_errno
    args = getattr(exc, "args", ())
    if args and isinstance(args[0], int):
        return args[0]
    return None


def driver_failure_from_exception(exc: BaseException, *, operation: str) -> DriverFailure:
    """Map an adapter exception without copying its potentially sensitive text."""

    if isinstance(exc, DriverFailure):
        return exc
    if isinstance(exc, asyncio.CancelledError):
        return DriverFailure(DriverFailureKind.CANCELLED)
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return DriverFailure(DriverFailureKind.TIMEOUT)
    if isinstance(exc, (ValueError, TypeError)):
        return DriverFailure(DriverFailureKind.PARAMETER)
    errno = _errno_from_exception(exc)
    if errno in {1045, 1698, 28000}:
        return DriverFailure(DriverFailureKind.AUTHENTICATION, errno=errno)
    if errno == 1049:
        return DriverFailure(DriverFailureKind.DATABASE_NOT_FOUND, errno=errno)
    if operation == "connect":
        return DriverFailure(DriverFailureKind.CONNECTION, errno=errno)
    if isinstance(exc, (ConnectionError, OSError)):
        return DriverFailure(DriverFailureKind.CONNECTION, errno=errno)
    return DriverFailure(DriverFailureKind.EXECUTION, errno=errno)


__all__ = [
    "DriverColumn",
    "DriverConnection",
    "DriverCursor",
    "DriverFactory",
    "DriverFailure",
    "DriverRow",
    "QueryKiller",
    "driver_failure_from_exception",
]
