"""Secret-free target metadata derived from configuration and the live session."""

from __future__ import annotations

from typing import TYPE_CHECKING

from dm_client.domain.results import TargetMetadata

if TYPE_CHECKING:
    from dm_client.domain.configuration import DmConnectionConfig
    from dm_client.ports.driver import DmConnection


def build_target(
    label: str,
    config: DmConnectionConfig,
    connection: DmConnection,
) -> TargetMetadata:
    """Build target identity without copying credentials."""

    return TargetMetadata(
        label=label,
        host=config.host,
        port=config.port,
        schema=connection.current_schema,
        server_version=connection.server_version,
    )


__all__ = ["build_target"]
