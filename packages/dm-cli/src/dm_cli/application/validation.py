"""Real connection validation for stored Dameng profiles."""

from __future__ import annotations

from typing import TYPE_CHECKING

from dm_client import DmConnectionConfig, DmSession

if TYPE_CHECKING:
    from dm_client import DriverFactory


class DmSessionValidator:
    """Validate a profile by opening and closing one real DM session."""

    def __init__(self, driver_factory: DriverFactory) -> None:
        self._driver_factory = driver_factory

    async def validate(self, config: DmConnectionConfig) -> None:
        async with DmSession(config, self._driver_factory, target_label=config.host):
            return


__all__ = ["DmSessionValidator"]
