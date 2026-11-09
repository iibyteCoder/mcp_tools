"""Synchronous driver port used by execution modules and DM adapters."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, TypeAlias

if TYPE_CHECKING:
    from dm_client.domain.configuration import DmConnectionConfig
    from dm_client.domain.values import DatabaseParameters, DatabaseValue


@dataclass(frozen=True, slots=True)
class DriverColumn:
    """Driver-neutral column metadata after adapter normalization."""

    name: str
    type_name: str
    nullable: bool = True
    default: DatabaseValue | None = None


DriverRow: TypeAlias = Sequence["DatabaseValue"]


class DmCursor(Protocol):
    """The small synchronous cursor surface needed by DM executors."""

    @property
    def description(self) -> Sequence[DriverColumn] | None: ...

    @property
    def rowcount(self) -> int: ...

    def execute(self, sql: str, parameters: DatabaseParameters = ()) -> None: ...

    def fetchmany(self, size: int) -> Sequence[DriverRow]: ...

    def close(self) -> None: ...


class DmConnection(Protocol):
    """The single-connection synchronous surface required by a DM session."""

    @property
    def user(self) -> str: ...

    @property
    def server_version(self) -> str: ...

    @property
    def current_schema(self) -> str: ...

    @property
    def str_case_sensitive(self) -> bool: ...

    @property
    def max_identifier_length(self) -> int: ...

    def cursor(self) -> DmCursor: ...

    def explain(self, sql: str) -> str: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...

    def close(self) -> None: ...


class DriverFactory(Protocol):
    """Create one isolated driver connection for a resolved target."""

    def connect(self, config: DmConnectionConfig) -> DmConnection: ...


__all__ = [
    "DmConnection",
    "DmCursor",
    "DriverColumn",
    "DriverFactory",
    "DriverRow",
]
