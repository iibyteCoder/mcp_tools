"""Application service for read-only schema inspection commands."""

from __future__ import annotations

from typing import TYPE_CHECKING

from dm_cli.application.results import InspectionCommandData
from dm_cli.domain.command import CommandAction, CommandGroup, CommandRequest, CommandStatus
from dm_client import (
    DmSession,
    InvalidArgumentError,
    SchemaDatabasesRequest,
    SchemaDescribeRequest,
    SchemaIndexesRequest,
    SchemaStatsRequest,
    SchemaTablesRequest,
)

if TYPE_CHECKING:
    from dm_cli.application.profile import ProfileService
    from dm_client import DriverFactory, InspectionRequest, InspectionResponse


class SchemaInspectionService:
    """Resolve one profile and execute a schema inspection command."""

    def __init__(self, profiles: ProfileService, driver_factory: DriverFactory) -> None:
        self._profiles = profiles
        self._driver_factory = driver_factory

    async def execute(self, request: CommandRequest) -> InspectionCommandData:
        if request.group is not CommandGroup.SCHEMA:
            raise InvalidArgumentError("schema inspection service accepts the schema command group only")
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
    if request.action is CommandAction.DATABASES:
        return SchemaDatabasesRequest(include_all=request.schema_all)
    if request.action is CommandAction.TABLES:
        return SchemaTablesRequest(schema=request.schema_name)
    if request.action is CommandAction.DESCRIBE:
        if request.schema_table is None:
            raise InvalidArgumentError("schema describe requires --table")
        return SchemaDescribeRequest(table=request.schema_table, schema=request.schema_name)
    if request.action is CommandAction.INDEXES:
        if request.schema_table is None:
            raise InvalidArgumentError("schema indexes requires --table")
        return SchemaIndexesRequest(table=request.schema_table, schema=request.schema_name)
    if request.action is CommandAction.STATS:
        return SchemaStatsRequest(table=request.schema_table, schema=request.schema_name)
    raise InvalidArgumentError("unsupported schema inspection action")


__all__ = ["SchemaInspectionService"]
