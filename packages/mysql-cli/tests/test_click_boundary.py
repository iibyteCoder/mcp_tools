from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

from click.testing import CliRunner

from mysql_cli.adapters.profile_store import JsonProfileStore
from mysql_cli.application.profile import ProfileService
from mysql_cli.application.results import SqlCommandData
from mysql_cli.application.runner import CliRuntime
from mysql_cli.domain.command import CommandAction, CommandGroup, CommandRequest, CommandStatus
from mysql_cli.domain.profile import ProfileName
from mysql_cli.ports.secret_store import SecretStore
from mysql_cli.presentation.click.app import cli
from mysql_client import ExecutionMetadata, SqlStatementType, TransactionAction, WriteResult

if TYPE_CHECKING:
    from pathlib import Path

    from mysql_cli.application.input import LoadedInputs


@dataclass
class MemorySecretStore(SecretStore):
    values: dict[ProfileName, str]

    def get(self, name: ProfileName) -> str | None:
        return self.values.get(name)

    def set(self, name: ProfileName, password: str) -> None:
        self.values[name] = password

    def delete(self, name: ProfileName) -> None:
        self.values.pop(name, None)


@dataclass
class FakeSqlService:
    requests: list[CommandRequest] = field(default_factory=list)

    async def execute(self, request: CommandRequest, inputs: LoadedInputs) -> SqlCommandData:
        self.requests.append(request)
        return SqlCommandData(
            status=CommandStatus.COMPLETED,
            command_group=CommandGroup.SQL,
            action=request.action,
            profile=request.selected_profile.value if request.selected_profile is not None else "dev",
            result=WriteResult(
                affected_rows=0,
                metadata=ExecutionMetadata(statement_type=SqlStatementType.UPDATE, duration_ms=0.0),
            ),
        )


def test_help_is_available_from_click_command_tree() -> None:
    runner = CliRunner()

    root_help = runner.invoke(cli, ["--help"])
    command_help = runner.invoke(cli, ["sql", "--help"])

    assert root_help.exit_code == 0
    assert command_help.exit_code == 0
    assert root_help.stderr == ""
    assert "profile" in root_help.stdout
    assert "read" in command_help.stdout


def test_click_usage_errors_are_one_json_document() -> None:
    result = CliRunner().invoke(cli, ["sql", "read"])

    assert result.exit_code == 2
    assert result.stderr == ""
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_argument"
    assert payload["error"]["details"][0]["error_type"] == "missing_sql"


def test_profile_set_uses_click_values_and_keeps_password_out_of_output(tmp_path: Path) -> None:
    profiles = ProfileService(
        JsonProfileStore(tmp_path / "profiles.json"),
        MemorySecretStore({}),
        working_directory=tmp_path,
    )

    result = CliRunner().invoke(
        cli,
        ["profile", "set", "dev", "--host", "db.example", "--user", "alice", "--password", "secret"],
        obj=CliRuntime(profile_service=profiles),
    )

    assert result.exit_code == 0
    assert "secret" not in result.stdout
    assert json.loads(result.stdout)["data"]["profile"]["name"] == "dev"


def test_sql_click_boundary_builds_typed_request() -> None:
    service = FakeSqlService()
    runtime = CliRuntime(profile_service=cast("ProfileService", object()), sql_service=service)

    result = CliRunner().invoke(
        cli,
        [
            "--profile",
            "dev",
            "sql",
            "write",
            "--sql",
            "UPDATE items SET id = 1",
            "--transaction",
            "rollback",
            "--timeout",
            "2",
        ],
        obj=runtime,
    )

    assert result.exit_code == 0
    request = service.requests[0]
    assert request.action is CommandAction.WRITE
    assert request.selected_profile == ProfileName(value="dev")
    assert request.sql_transaction is TransactionAction.ROLLBACK
    assert request.sql_timeout_seconds == 2.0


def test_selected_benchmark_is_validated_before_execution() -> None:
    service = FakeSqlService()
    runtime = CliRuntime(profile_service=cast("ProfileService", object()), sql_service=service)

    result = CliRunner().invoke(
        cli,
        ["--profile", "dev", "sql", "benchmark", "--sql", "UPDATE items SET id = 1"],
        obj=runtime,
    )

    assert result.exit_code == 2
    assert json.loads(result.stdout)["error"]["code"] == "unsupported_sql"
    assert service.requests == []


def test_selected_compare_validates_both_inputs_before_execution() -> None:
    service = FakeSqlService()
    runtime = CliRuntime(profile_service=cast("ProfileService", object()), sql_service=service)

    result = CliRunner().invoke(
        cli,
        [
            "--profile",
            "dev",
            "sql",
            "compare",
            "--left-sql",
            "SELECT 1",
            "--right-sql",
            "UPDATE items SET id = 1",
        ],
        obj=runtime,
    )

    assert result.exit_code == 2
    assert json.loads(result.stdout)["error"]["code"] == "unsupported_sql"
    assert service.requests == []
