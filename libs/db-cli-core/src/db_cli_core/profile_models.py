"""Value objects for named connections and directory resolution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from db_cli_core.types import JsonScalar

if TYPE_CHECKING:
    from pathlib import Path

    from db_cli_core.enums import ConnectionSource, DatabaseKind

ConnectionSettings = dict[str, JsonScalar]


@dataclass(frozen=True)
class ConnectionProfile:
    name: str
    database_kind: DatabaseKind
    settings: ConnectionSettings


@dataclass(frozen=True)
class ConnectionSelection:
    profile: ConnectionProfile
    source: ConnectionSource
    bound_directory: Path | None = None
