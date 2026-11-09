"""Application service for read-only server inspection commands."""

from __future__ import annotations

from typing import TYPE_CHECKING

from dm_cli.application.results import InspectionCommandData
from dm_cli.domain.command import CommandAction, CommandGroup, CommandRequest, CommandStatus
from dm_client import (
    DmSession,
    InvalidArgumentError,
    ServerCapabilitiesRequest,
    ServerInspectRequest,
    ServerParametersRequest,
)

if TYPE_CHECKING:
    from dm_cli.application.profile import ProfileService
    from dm_client import DriverFactory, InspectionRequest, InspectionResponse


class ServerInspectionService:
    """Resolve one profile and execute a server inspection command."""

    def __init__(self, profiles: ProfileService, driver_factory: DriverFactory) -> None:
        self._profiles = profiles
        self._driver_factory = driver_factory

    async def execute(self, request: CommandRequest) -> InspectionCommandData:
        if request.group is not CommandGroup.SERVER:
            raise InvalidArgumentError("server inspection service accepts the server command group only")
        client_request = _client_request(request)
        selection = self._profiles.selection(request.selected_profile)
        profile = selection.profile
        config = self._profiles.connection_config(profile)

        async with DmSession(
            config,
            self._driver_factory,
            target_label=profile.name.value,
        ) as session:
            result: InspectionResponse = await session.execute_inspection(client_request)
        return InspectionCommandData(
            status=CommandStatus.COMPLETED,
            command_group=request.group,
            action=request.action,
            profile=profile.name.value,
            result=result,
        )


def _client_request(request: CommandRequest) -> InspectionRequest:
    if request.action is CommandAction.INSPECT:
        return ServerInspectRequest()
    if request.action is CommandAction.CAPABILITIES:
        return ServerCapabilitiesRequest()
    if request.action is CommandAction.PARAMETERS:
        return ServerParametersRequest(
            name_filter=request.parameters_filter,
            include_all=request.parameters_include_all,
        )
    raise InvalidArgumentError("unsupported server inspection action")


__all__ = ["ServerInspectionService"]
