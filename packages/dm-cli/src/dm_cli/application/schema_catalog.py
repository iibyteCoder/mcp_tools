"""Application service for DM catalog DDL, constraints and object commands."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from dm_cli.application.results import InspectionCommandData
from dm_cli.domain.command import CommandAction, CommandGroup, CommandRequest, CommandStatus
from dm_client import (
    DmSession,
    InvalidArgumentError,
    ObjectType,
    SchemaConstraintsRequest,
    SchemaDdlRequest,
    SchemaObjectsRequest,
)

if TYPE_CHECKING:
    from dm_cli.application.profile import ProfileService
    from dm_client import CatalogRequest, DdlResult, DriverFactory, InspectionRequest, InspectionResponse

_CATALOG_ACTIONS: Final[frozenset[CommandAction]] = frozenset(
    {CommandAction.DDL, CommandAction.CONSTRAINTS, CommandAction.OBJECTS}
)


class SchemaCatalogService:
    """Resolve one profile and execute a schema catalog command."""

    def __init__(self, profiles: ProfileService, driver_factory: DriverFactory) -> None:
        self._profiles = profiles
        self._driver_factory = driver_factory

    async def execute(self, request: CommandRequest) -> InspectionCommandData:
        if request.group is not CommandGroup.SCHEMA:
            raise InvalidArgumentError("schema catalog service accepts the schema command group only")
        if request.action not in _CATALOG_ACTIONS:
            raise InvalidArgumentError("unsupported schema catalog action")
        client_request = _client_request(request)
        selection = self._profiles.selection(request.selected_profile)
        profile = selection.profile
        config = self._profiles.connection_config(profile)

        async with DmSession(
            config,
            self._driver_factory,
            target_label=profile.name.value,
        ) as session:
            result: DdlResult | InspectionResponse
            if isinstance(client_request, SchemaDdlRequest):
                result = await session.execute_catalog(client_request)
            else:
                result = await session.execute_inspection(client_request)
        return InspectionCommandData(
            status=CommandStatus.COMPLETED,
            command_group=request.group,
            action=request.action,
            profile=profile.name.value,
            result=result,
        )


def _client_request(request: CommandRequest) -> CatalogRequest | InspectionRequest:
    if request.action is CommandAction.DDL:
        if request.schema_object_name is None:
            raise InvalidArgumentError("schema ddl requires --name")
        return SchemaDdlRequest(
            object_type=request.schema_object_type or ObjectType.TABLE,
            name=request.schema_object_name,
            schema=request.schema_name,
        )
    if request.action is CommandAction.CONSTRAINTS:
        return SchemaConstraintsRequest(table=request.schema_table, schema=request.schema_name)
    if request.action is CommandAction.OBJECTS:
        return SchemaObjectsRequest(object_type=request.schema_object_type, schema=request.schema_name)
    raise InvalidArgumentError("unsupported schema catalog action")


__all__ = ["SchemaCatalogService"]
