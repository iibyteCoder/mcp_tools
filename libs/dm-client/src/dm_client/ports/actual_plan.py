"""Port for collecting an estimated plan with actual aggregate statistics."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from dm_client.domain.configuration import DmConnectionConfig
    from dm_client.domain.results import ActualPlanResult


class ActualPlanRunner(Protocol):
    """Collect one estimated plan and its actual aggregate runtime statistics."""

    async def collect(
        self,
        config: DmConnectionConfig,
        sql: str,
        *,
        target_label: str,
        timeout_seconds: float | None,
    ) -> ActualPlanResult:
        """Return the estimated plan and actual aggregate ``Statistics`` block."""
        ...


__all__ = ["ActualPlanRunner"]
