"""Application service for read-only server and schema inspection."""

from __future__ import annotations

from typing import TYPE_CHECKING

from mysql_cli.command_model import CommandAction, CommandGroup, CommandRequest, CommandStatus
from mysql_cli.output_model import InspectionCommandData
from mysql_client import (
    AiomysqlDriverFactory,
    DriverFactory,
    MySqlSession,
    SchemaDatabasesRequest,
    SchemaDescribeRequest,
    SchemaIndexesRequest,
    SchemaStatsRequest,
    SchemaTablesRequest,
    ServerCapabilitiesRequest,
    ServerInspectRequest,
    TableName,
)

if TYPE_CHECKING:
    from mysql_cli.profile_service import ProfileService
    from mysql_client.request_models import InspectionRequest


class InspectionService:
    """Resolve one selected profile and execute one read-only inspection."""

    def __init__(self, profiles: ProfileService, driver_factory: DriverFactory | None = None) -> None:
        self._profiles = profiles
        self._driver_factory = driver_factory or AiomysqlDriverFactory()

    async def execute(self, request: CommandRequest) -> InspectionCommandData:
        """Execute the requested inspection without changing profile or database state."""

        if request.group not in {CommandGroup.SERVER, CommandGroup.SCHEMA}:
            raise ValueError("inspection service 只接受 server 或 schema 命令")
        inspection_request = _inspection_request(request)
        selection = self._profiles.selection(request.selected_profile)
        config = self._profiles.connection_config(selection.profile)
        async with MySqlSession(
            config,
            self._driver_factory,
            target_label=selection.profile.name.value,
        ) as session:
            result = await session.execute_inspection(inspection_request)
        return InspectionCommandData(
            status=CommandStatus.COMPLETED,
            command_group=request.group,
            action=request.action,
            profile=selection.profile.name.value,
            result=result,
        )


def _inspection_request(request: CommandRequest) -> InspectionRequest:
    if request.group is CommandGroup.SERVER and request.action is CommandAction.INSPECT:
        return ServerInspectRequest()
    if request.group is CommandGroup.SERVER and request.action is CommandAction.CAPABILITIES:
        return ServerCapabilitiesRequest()
    if request.group is not CommandGroup.SCHEMA:
        raise ValueError("不是 inspection 命令")
    if request.action is CommandAction.DATABASES:
        return SchemaDatabasesRequest()
    if request.action is CommandAction.TABLES:
        return SchemaTablesRequest(database=request.schema_database)
    if request.action is CommandAction.DESCRIBE:
        return SchemaDescribeRequest(
            database=request.schema_database,
            table=_required_table(request),
        )
    if request.action is CommandAction.INDEXES:
        return SchemaIndexesRequest(
            database=request.schema_database,
            table=_required_table(request),
        )
    if request.action is CommandAction.STATS:
        return SchemaStatsRequest(
            database=request.schema_database,
            table=request.schema_table,
        )
    raise ValueError("不支持的 schema 命令")


def _required_table(request: CommandRequest) -> TableName:
    if request.schema_table is None:
        raise ValueError("schema table is required")
    return request.schema_table


__all__ = ["InspectionService"]
