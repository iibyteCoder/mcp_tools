from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

from click.testing import CliRunner

from db_cli_kit.profiles import ProfileName
from mysql_cli.application.results import SchemaAnalyzeCommandData
from mysql_cli.application.runner import CliRuntime
from mysql_cli.domain.command import CommandAction, CommandGroup, CommandRequest, CommandStatus
from mysql_cli.presentation.click.app import cli
from mysql_client import (
    AnalyzeTableResult,
    AnalyzeTableRow,
    DatabaseName,
    ExecutionMetadata,
    SqlStatementType,
    TableName,
)

if TYPE_CHECKING:
    from mysql_cli.application.profile import ProfileService


@dataclass
class FakeSchemaMaintenanceService:
    requests: list[CommandRequest] = field(default_factory=list)

    async def execute(self, request: CommandRequest) -> SchemaAnalyzeCommandData:
        self.requests.append(request)
        return SchemaAnalyzeCommandData(
            status=CommandStatus.COMPLETED,
            command_group=request.group,
            action=request.action,
            profile="dev",
            result=AnalyzeTableResult(
                rows=(
                    AnalyzeTableRow(
                        table_name="billing.invoices",
                        operation="analyze",
                        message_type="status",
                        message="OK",
                    ),
                ),
                metadata=ExecutionMetadata(statement_type=SqlStatementType.DDL, duration_ms=0.0),
            ),
        )


def runtime(service: FakeSchemaMaintenanceService) -> CliRuntime:
    return CliRuntime(
        profile_service=cast("ProfileService", object()),
        schema_maintenance_service=service,
    )


def test_schema_analyze_is_routed_with_typed_target_and_timeout() -> None:
    service = FakeSchemaMaintenanceService()

    result = CliRunner().invoke(
        cli,
        [
            "--profile",
            "dev",
            "schema",
            "analyze",
            "--database",
            "billing",
            "--table",
            "invoices",
            "--timeout",
            "2.5",
        ],
        obj=runtime(service),
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["data"]["command_group"] == "schema"
    assert payload["data"]["action"] == "analyze"
    assert payload["data"]["result"]["rows"] == [
        {
            "table_name": "billing.invoices",
            "operation": "analyze",
            "message_type": "status",
            "message": "OK",
        }
    ]
    assert payload["data"]["result"]["metadata"]["statement_type"] == "ddl"
    request = service.requests[0]
    assert request.group is CommandGroup.SCHEMA
    assert request.action is CommandAction.ANALYZE
    assert request.selected_profile == ProfileName(value="dev")
    assert request.schema_database == DatabaseName(value="billing")
    assert request.schema_table == TableName(value="invoices")
    assert request.schema_timeout_seconds == 2.5


def test_schema_analyze_requires_table() -> None:
    service = FakeSchemaMaintenanceService()

    result = CliRunner().invoke(cli, ["--profile", "dev", "schema", "analyze"], obj=runtime(service))

    assert result.exit_code == 2
    assert json.loads(result.stdout)["error"]["code"] == "invalid_argument"
    assert service.requests == []


def test_schema_analyze_timeout_must_be_positive() -> None:
    service = FakeSchemaMaintenanceService()

    result = CliRunner().invoke(
        cli,
        ["--profile", "dev", "schema", "analyze", "--table", "invoices", "--timeout", "0"],
        obj=runtime(service),
    )

    assert result.exit_code == 2
    assert json.loads(result.stdout)["error"]["code"] == "invalid_argument"
    assert service.requests == []


def test_schema_analyze_help_states_maintenance_effects() -> None:
    result = CliRunner().invoke(cli, ["schema", "analyze", "--help"])

    assert result.exit_code == 0
    help_text = " ".join(result.stdout.split())
    assert "ANALYZE TABLE" in help_text
    assert "not a read-only query" in help_text
    assert "may take metadata locks" in help_text
    assert "--transaction" not in help_text


def test_schema_analyze_has_no_transaction_option() -> None:
    service = FakeSchemaMaintenanceService()

    result = CliRunner().invoke(
        cli,
        ["--profile", "dev", "schema", "analyze", "--table", "invoices", "--transaction", "commit"],
        obj=runtime(service),
    )

    assert result.exit_code == 2
    assert json.loads(result.stdout)["error"]["code"] == "invalid_argument"
    assert service.requests == []
