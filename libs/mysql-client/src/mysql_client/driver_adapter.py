"""Typed driver boundary; incomplete aiomysql types stay in this module."""

from __future__ import annotations

import asyncio
import importlib
from collections.abc import Awaitable, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, cast, runtime_checkable

from mysql_client.enums import DriverFailureKind

if TYPE_CHECKING:
    from mysql_client.configuration import MySqlConnectionConfig
    from mysql_client.value_models import DatabaseParameters, DatabaseValue


class _RawCursor(Protocol):
    """Minimal structural surface exposed by an aiomysql cursor."""

    @property
    def description(self) -> Sequence[object] | None: ...

    @property
    def rowcount(self) -> object: ...

    @property
    def lastrowid(self) -> object: ...

    def execute(self, sql: str, parameters: DatabaseParameters) -> Awaitable[object]: ...

    def fetchmany(self, size: int) -> Awaitable[Sequence[object]]: ...


class _RawCursorContext(Protocol):
    async def __aenter__(self) -> _RawCursor: ...

    async def __aexit__(self, exc_type: object, exc_value: object, traceback: object) -> bool | None: ...


class _RawConnection(Protocol):
    def thread_id(self) -> object: ...

    def cursor(self) -> _RawCursorContext: ...

    def begin(self) -> object: ...

    def commit(self) -> object: ...

    def rollback(self) -> object: ...

    def close(self) -> object: ...

    def wait_closed(self) -> object: ...


class _AiomysqlModule(Protocol):
    def connect(
        self,
        *,
        host: str,
        port: int,
        user: str,
        password: str,
        db: str | None,
        charset: str,
        connect_timeout: float,
        read_timeout: float,
        autocommit: bool,
    ) -> Awaitable[_RawConnection]: ...


@dataclass(frozen=True, slots=True, kw_only=True)
class DriverColumn:
    """Driver-neutral column metadata after adapter normalization."""

    name: str
    type_name: str
    nullable: bool = True
    default: DatabaseValue | None = None


DriverRow = Sequence[object]


class DriverFailure(Exception):
    """Non-secret failure information translated by a concrete adapter."""

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


class AiomysqlDriverFactory:
    """Adapt aiomysql to the narrow typed driver protocols."""

    async def connect(self, config: MySqlConnectionConfig) -> DriverConnection:
        try:
            module = cast("_AiomysqlModule", importlib.import_module("aiomysql"))
            raw_connection = await module.connect(
                host=config.host,
                port=config.port,
                user=config.user,
                password=config.password.reveal(),
                db=config.database,
                charset=config.charset,
                connect_timeout=config.connect_timeout_seconds,
                read_timeout=config.read_timeout_seconds,
                autocommit=False,
            )
        except asyncio.CancelledError:
            raise
        except BaseException as exc:
            raise driver_failure_from_exception(exc, operation="connect") from exc
        return _AiomysqlConnectionAdapter(raw_connection)

    async def kill_query(self, config: MySqlConnectionConfig, thread_id: int) -> bool:
        control: DriverConnection | None = None
        try:
            control = await self.connect(config)
            async with control.cursor() as cursor:
                await cursor.execute("KILL QUERY %s", (thread_id,))
            return True
        except (DriverFailure, asyncio.TimeoutError, OSError):
            return False
        finally:
            if control is not None:
                await control.close()


class _AiomysqlConnectionAdapter:
    def __init__(self, raw_connection: _RawConnection) -> None:
        self._raw_connection = raw_connection

    @property
    def thread_id(self) -> int | None:
        try:
            value = self._raw_connection.thread_id()
        except (AttributeError, TypeError):
            return None
        return value if isinstance(value, int) else None

    def cursor(self) -> AbstractAsyncContextManager[DriverCursor]:
        try:
            context = self._raw_connection.cursor()
        except asyncio.CancelledError:
            raise
        except BaseException as exc:
            raise driver_failure_from_exception(exc, operation="cursor") from exc
        return _AiomysqlCursorContext(context)

    async def begin(self) -> None:
        await self._call_async_or_sync("begin")

    async def commit(self) -> None:
        await self._call_async_or_sync("commit")

    async def rollback(self) -> None:
        await self._call_async_or_sync("rollback")

    async def close(self) -> None:
        try:
            result = self._raw_connection.close()
            if hasattr(result, "__await__"):
                await result
            wait_closed = getattr(self._raw_connection, "wait_closed", None)
            if callable(wait_closed):
                result = wait_closed()
                if hasattr(result, "__await__"):
                    await result
        except asyncio.CancelledError:
            raise
        except BaseException as exc:
            raise driver_failure_from_exception(exc, operation="close") from exc

    async def _call_async_or_sync(self, name: str) -> None:
        try:
            method = getattr(self._raw_connection, name)
            result = method()
            if hasattr(result, "__await__"):
                await result
        except asyncio.CancelledError:
            raise
        except BaseException as exc:
            raise driver_failure_from_exception(exc, operation=name) from exc


class _AiomysqlCursorContext(AbstractAsyncContextManager[DriverCursor]):
    def __init__(self, raw_context: _RawCursorContext) -> None:
        self._raw_context = raw_context

    async def __aenter__(self) -> DriverCursor:
        try:
            raw_cursor = await self._raw_context.__aenter__()
        except asyncio.CancelledError:
            raise
        except BaseException as exc:
            raise driver_failure_from_exception(exc, operation="cursor") from exc
        return _AiomysqlCursorAdapter(raw_cursor)

    async def __aexit__(self, exc_type: object, exc_value: object, traceback: object) -> bool | None:
        try:
            return await self._raw_context.__aexit__(exc_type, exc_value, traceback)
        except asyncio.CancelledError:
            raise
        except BaseException as exc:
            raise driver_failure_from_exception(exc, operation="cursor") from exc


class _AiomysqlCursorAdapter:
    def __init__(self, raw_cursor: _RawCursor) -> None:
        self._raw_cursor = raw_cursor

    @property
    def description(self) -> Sequence[DriverColumn] | None:
        raw_description = getattr(self._raw_cursor, "description", None)
        if raw_description is None:
            return None
        return tuple(_column_from_raw(item) for item in raw_description)

    @property
    def rowcount(self) -> int:
        value = getattr(self._raw_cursor, "rowcount", 0)
        return value if isinstance(value, int) else 0

    @property
    def lastrowid(self) -> int | None:
        value = getattr(self._raw_cursor, "lastrowid", None)
        return value if isinstance(value, int) else None

    async def execute(self, sql: str, parameters: DatabaseParameters) -> None:
        try:
            await self._raw_cursor.execute(sql, parameters)
        except asyncio.CancelledError:
            raise
        except BaseException as exc:
            raise driver_failure_from_exception(exc, operation="execute") from exc

    async def fetchmany(self, size: int) -> Sequence[DriverRow]:
        try:
            rows = await self._raw_cursor.fetchmany(size)
        except asyncio.CancelledError:
            raise
        except BaseException as exc:
            raise driver_failure_from_exception(exc, operation="fetch") from exc
        return cast("Sequence[DriverRow]", rows)


def _column_from_raw(raw: object) -> DriverColumn:
    if isinstance(raw, tuple) and raw:
        name = str(raw[0])
        type_name = str(raw[1]) if len(raw) > 1 else "UNKNOWN"
        nullable = bool(raw[6]) if len(raw) > 6 else True
        return DriverColumn(name=name, type_name=type_name, nullable=nullable)
    name = str(getattr(raw, "name", ""))
    type_code = getattr(raw, "type_code", "UNKNOWN")
    nullable = bool(getattr(raw, "null_ok", True))
    return DriverColumn(name=name, type_name=str(type_code), nullable=nullable)
