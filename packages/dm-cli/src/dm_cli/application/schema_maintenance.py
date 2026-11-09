"""Application service for the DM statistics maintenance command."""

from __future__ import annotations

from typing import TYPE_CHECKING

from dm_cli.application.results import InspectionCommandData
from dm_cli.domain.command import CommandAction, CommandGroup, CommandRequest, CommandStatus
from dm_client import DmSession, InvalidArgumentError, SchemaAnalyzeRequest

if TYPE_CHECKING:
    from dm_cli.application.profile import ProfileService
    from dm_client import AnalyzeResult, DriverFactory


class SchemaMaintenanceService:
    """Resolve one profile and execute one table-level analysis."""

    def __init__(self, profiles: ProfileService, driver_factory: DriverFactory) -> None:
        self._profiles = profiles
        self._driver_factory = driver_factory

    async def execute(self, request: CommandRequest) -> InspectionCommandData:
        if request.group is not CommandGroup.SCHEMA:
            raise InvalidArgumentError("schema maintenance service accepts the schema command group only")
        client_request = _client_request(request)
        selection = self._profiles.selection(request.selected_profile)
        profile = selection.profile
        config = self._profiles.connection_config(profile)

        async with DmSession(
            config,
            self._driver_factory,
            target_label=profile.name.value,
        ) as session:
            result: AnalyzeResult = await session.execute_maintenance(client_request)
        return InspectionCommandData(
            status=CommandStatus.COMPLETED,
            command_group=request.group,
            action=request.action,
            profile=profile.name.value,
            result=result,
        )


def _client_request(request: CommandRequest) -> SchemaAnalyzeRequest:
    if request.action is not CommandAction.ANALYZE:
        raise InvalidArgumentError("unsupported schema maintenance action")
    if request.schema_table is None:
        raise InvalidArgumentError("schema analyze requires --table")
    try:
        return SchemaAnalyzeRequest(
            table=request.schema_table,
            schema=request.schema_name,
            partition=request.schema_partition,
            estimate_percent=request.schema_estimate_percent,
            cascade=True if request.schema_cascade is None else request.schema_cascade,
            degree=request.schema_degree,
        )
    except ValueError as exc:
        raise InvalidArgumentError("schema analyze options are invalid") from exc


__all__ = ["SchemaMaintenanceService"]
