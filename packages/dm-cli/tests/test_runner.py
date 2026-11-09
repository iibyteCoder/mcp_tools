"""Unit tests for SQL request orchestration and profile selection."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest

from db_cli_kit.profiles import ProfileName
from dm_cli.adapters.profile_store import JsonProfileStore
from dm_cli.application.profile import ProfileService, ProfileServiceError, ProfileServiceErrorCode
from dm_cli.application.results import CommandDiagnosticData, SqlCommandData
from dm_cli.application.runner import CliRuntime, execute_request
from dm_cli.domain.command import (
    CommandAction,
    CommandGroup,
    CommandRequest,
    CommandStatus,
    SqlInputSpec,
)
from dm_cli.domain.profile import ProfileSetRequest, ProfileSettingsPatch
from dm_cli.ports.secret_store import SecretStore
from dm_client.domain.enums import SqlStatementType
from dm_client.domain.results import ExecutionMetadata, QueryResult

if TYPE_CHECKING:
    from pathlib import Path

    from dm_cli.application.input import LoadedInputs
    from dm_cli.domain.profile import ProfileSelection


@dataclass
class MemorySecretStore(SecretStore):
    """In-memory credential store; tests never touch the real keyring."""

    values: dict[ProfileName, str] = field(default_factory=dict)

    def get(self, name: ProfileName) -> str | None:
        return self.values.get(name)

    def set(self, name: ProfileName, password: str) -> None:
        self.values[name] = password

    def delete(self, name: ProfileName) -> None:
        self.values.pop(name, None)


class FakeSqlExecutor:
    """Record SQL service calls and return a typed completed result."""

    def __init__(self) -> None:
        self.calls: list[tuple[CommandRequest, LoadedInputs]] = []

    async def execute(self, request: CommandRequest, inputs: LoadedInputs) -> SqlCommandData:
        self.calls.append((request, inputs))
        return SqlCommandData(
            status=CommandStatus.COMPLETED,
            command_group=request.group,
            action=request.action,
            profile="dev",
            result=QueryResult(
                columns=(),
                rows=(),
                metadata=ExecutionMetadata(
                    statement_type=SqlStatementType.SELECT,
                    duration_ms=0.0,
                ),
            ),
        )


class FakeActualPlanExecutor:
    """Record actual-plan service calls and return a typed completed result."""

    def __init__(self) -> None:
        self.calls: list[tuple[CommandRequest, LoadedInputs]] = []

    async def execute(self, request: CommandRequest, inputs: LoadedInputs) -> SqlCommandData:
        self.calls.append((request, inputs))
        return SqlCommandData(
            status=CommandStatus.COMPLETED,
            command_group=request.group,
            action=request.action,
            profile="dev",
            result=QueryResult(
                columns=(),
                rows=(),
                metadata=ExecutionMetadata(
                    statement_type=SqlStatementType.SELECT,
                    duration_ms=0.0,
                ),
            ),
        )


class FailingProfileService:
    """Raise a non-NOT_FOUND selection failure for propagation coverage."""

    def selection(self, explicit: ProfileName | None, *, directory: Path | None = None) -> ProfileSelection:
        del explicit, directory
        raise ProfileServiceError(ProfileServiceErrorCode.CONFLICT, "profile registry changed")


def make_runtime(tmp_path: Path) -> tuple[CliRuntime, FakeSqlExecutor, ProfileService]:
    profiles = ProfileService(
        JsonProfileStore(tmp_path / "profiles.json", lock_timeout=0.0),
        MemorySecretStore(),
        working_directory=tmp_path,
    )
    profiles.set(
        ProfileSetRequest(
            name=ProfileName(value="dev"),
            settings=ProfileSettingsPatch(host="127.0.0.1", user="APP", schema="APP"),
            password="never-print-this",
        )
    )
    sql_service = FakeSqlExecutor()
    return CliRuntime(profile_service=profiles, sql_service=sql_service), sql_service, profiles


def read_request() -> CommandRequest:
    return CommandRequest(
        group=CommandGroup.SQL,
        action=CommandAction.READ,
        sql_input=SqlInputSpec.inline("SELECT 1"),
    )


def explain_request(*, actual: bool) -> CommandRequest:
    return CommandRequest(
        group=CommandGroup.SQL,
        action=CommandAction.EXPLAIN,
        selected_profile=ProfileName(value="dev"),
        sql_input=SqlInputSpec.inline("SELECT 1"),
        sql_explain_actual=actual,
    )


def test_bound_directory_without_explicit_profile_executes_sql(tmp_path: Path) -> None:
    runtime, sql_service, profiles = make_runtime(tmp_path)
    profiles.bind(ProfileName(value="dev"), tmp_path)

    data = asyncio.run(execute_request(runtime, read_request(), stdin_text=None))

    assert len(sql_service.calls) == 1
    called_request, called_inputs = sql_service.calls[0]
    assert called_request == read_request()
    assert called_request.selected_profile is None
    assert called_inputs.sql is not None
    assert isinstance(data, SqlCommandData)


def test_no_binding_without_explicit_profile_returns_the_local_diagnostic(tmp_path: Path) -> None:
    runtime, sql_service, _ = make_runtime(tmp_path)

    data = asyncio.run(execute_request(runtime, read_request(), stdin_text=None))

    assert sql_service.calls == []
    assert isinstance(data, CommandDiagnosticData)
    assert data.sql is not None
    assert data.sql.statement_type is SqlStatementType.SELECT


def test_non_not_found_selection_failures_propagate(tmp_path: Path) -> None:
    sql_service = FakeSqlExecutor()
    runtime = CliRuntime(profile_service=FailingProfileService(), sql_service=sql_service)

    with pytest.raises(ProfileServiceError) as caught:
        asyncio.run(execute_request(runtime, read_request(), stdin_text=None))

    assert caught.value.code is ProfileServiceErrorCode.CONFLICT
    assert sql_service.calls == []


def test_actual_explain_dispatches_to_the_actual_plan_service(tmp_path: Path) -> None:
    runtime, sql_service, _ = make_runtime(tmp_path)
    actual_service = FakeActualPlanExecutor()
    runtime.actual_plan_service = actual_service

    data = asyncio.run(execute_request(runtime, explain_request(actual=True), stdin_text=None))

    assert len(actual_service.calls) == 1
    assert actual_service.calls[0][0] == explain_request(actual=True)
    assert sql_service.calls == []
    assert isinstance(data, SqlCommandData)


def test_estimated_explain_still_dispatches_to_the_sql_service(tmp_path: Path) -> None:
    runtime, sql_service, _ = make_runtime(tmp_path)
    actual_service = FakeActualPlanExecutor()
    runtime.actual_plan_service = actual_service

    asyncio.run(execute_request(runtime, explain_request(actual=False), stdin_text=None))

    assert len(sql_service.calls) == 1
    assert actual_service.calls == []
