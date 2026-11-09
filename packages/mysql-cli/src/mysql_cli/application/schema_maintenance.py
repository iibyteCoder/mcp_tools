"""Application service for the MySQL ``ANALYZE TABLE`` maintenance command."""

from __future__ import annotations

from typing import TYPE_CHECKING

from mysql_cli.application.results import SchemaAnalyzeCommandData
from mysql_cli.domain.command import CommandAction, CommandGroup, CommandRequest, CommandStatus
from mysql_client import AnalyzeTableRequest, InvalidArgumentError, MySqlSession

if TYPE_CHECKING:
    from mysql_cli.application.profile import ProfileService
    from mysql_client.ports.driver import DriverFactory


class SchemaMaintenanceService:
    """Resolve one selected profile and execute one ``ANALYZE TABLE`` statement."""

    def __init__(self, profiles: ProfileService, driver_factory: DriverFactory) -> None:
        self._profiles = profiles
        self._driver_factory = driver_factory

    async def execute(self, request: CommandRequest) -> SchemaAnalyzeCommandData:
        """Execute the requested table maintenance without autocommit calls."""

        if request.group is not CommandGroup.SCHEMA:
            raise InvalidArgumentError("schema maintenance service accepts the schema command group only")
        client_request = _analyze_request(request)
        selection = self._profiles.selection(request.selected_profile)
        config = self._profiles.connection_config(selection.profile)
        async with MySqlSession(
            config,
            self._driver_factory,
            target_label=selection.profile.name.value,
        ) as session:
            result = await session.execute_analyze(client_request)
        return SchemaAnalyzeCommandData(
            status=CommandStatus.COMPLETED,
            command_group=request.group,
            action=request.action,
            profile=selection.profile.name.value,
            result=result,
        )


def _analyze_request(request: CommandRequest) -> AnalyzeTableRequest:
    if request.action is not CommandAction.ANALYZE:
        raise InvalidArgumentError("unsupported schema maintenance action")
    if request.schema_table is None:
        raise InvalidArgumentError("schema analyze requires --table")
    try:
        return AnalyzeTableRequest(
            table=request.schema_table,
            database=request.schema_database,
            statement_timeout_seconds=request.schema_timeout_seconds,
        )
    except ValueError as exc:
        raise InvalidArgumentError("schema analyze options are invalid") from exc


__all__ = ["SchemaMaintenanceService"]
