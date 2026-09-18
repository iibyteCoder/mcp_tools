from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

import pytest
from click.testing import CliRunner

from mysql_cli.application.results import InspectionCommandData
from mysql_cli.application.runner import CliRuntime
from mysql_cli.domain.command import CommandAction, CommandGroup, CommandRequest, CommandStatus
from mysql_cli.domain.profile import ProfileName
from mysql_cli.presentation.click.app import cli
from mysql_client import (
    ColumnDefinition,
    DatabaseRow,
    ExecutionMetadata,
    InspectionCommand,
    InspectionResult,
    QueryResult,
    SqlStatementType,
)

if TYPE_CHECKING:
    from mysql_cli.application.profile import ProfileService


@dataclass
class FakeInspectionService:
    requests: list[CommandRequest] = field(default_factory=list)

    async def execute(self, request: CommandRequest) -> InspectionCommandData:
        self.requests.append(request)
        result = InspectionResult(
            command=InspectionCommand.SCHEMA_TABLES,
            query=QueryResult(
                columns=(ColumnDefinition(name="name", type_name="VARCHAR"),),
                rows=(DatabaseRow.from_values(("billing",)),),
                metadata=ExecutionMetadata(statement_type=SqlStatementType.SELECT, duration_ms=0.0),
            ),
        )
        return InspectionCommandData(
            status=CommandStatus.COMPLETED,
            command_group=request.group,
            action=request.action,
            profile="dev",
            result=result,
        )


def runtime(service: FakeInspectionService) -> CliRuntime:
    return CliRuntime(
        profile_service=cast("ProfileService", object()),
        inspection_service=service,
    )


@pytest.mark.parametrize(
    ("arguments", "group", "action"),
    [
        (["server", "inspect"], CommandGroup.SERVER, CommandAction.INSPECT),
        (["server", "capabilities"], CommandGroup.SERVER, CommandAction.CAPABILITIES),
        (["schema", "databases"], CommandGroup.SCHEMA, CommandAction.DATABASES),
        (["schema", "tables", "--database", "billing"], CommandGroup.SCHEMA, CommandAction.TABLES),
        (["schema", "describe", "--database", "billing", "--table", "invoices"], CommandGroup.SCHEMA, CommandAction.DESCRIBE),
        (["schema", "indexes", "--table", "invoices"], CommandGroup.SCHEMA, CommandAction.INDEXES),
        (["schema", "stats", "--table", "invoices"], CommandGroup.SCHEMA, CommandAction.STATS),
    ],
)
def test_inspection_routes_are_typed(
    arguments: list[str], group: CommandGroup, action: CommandAction
) -> None:
    service = FakeInspectionService()
    result = CliRunner().invoke(cli, ["--profile", "dev", *arguments], obj=runtime(service))

    assert result.exit_code == 0
    assert json.loads(result.stdout)["ok"] is True
    request = service.requests[0]
    assert request.group is group
    assert request.action is action
    assert request.selected_profile == ProfileName(value="dev")


def test_schema_targets_are_validated_at_click_boundary() -> None:
    service = FakeInspectionService()
    missing_table = CliRunner().invoke(cli, ["schema", "describe"], obj=runtime(service))
    invalid_database = CliRunner().invoke(cli, ["schema", "tables", "--database", "\x00"], obj=runtime(service))

    assert missing_table.exit_code == 2
    assert json.loads(missing_table.stdout)["error"]["code"] == "invalid_argument"
    assert invalid_database.exit_code == 2
    assert json.loads(invalid_database.stdout)["error"]["code"] == "invalid_argument"
    assert service.requests == []
