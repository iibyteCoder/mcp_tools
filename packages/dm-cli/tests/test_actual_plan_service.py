"""Unit tests for the actual-plan application service over a fake runner."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest

from db_cli_kit.profiles import ProfileName
from dm_cli.adapters.profile_store import JsonProfileStore
from dm_cli.application.actual_plan import ActualPlanService
from dm_cli.application.input import LoadedInputs, load_inputs
from dm_cli.application.profile import ProfileService
from dm_cli.domain.command import CommandAction, CommandGroup, CommandRequest, CommandStatus, SqlInputSpec
from dm_cli.domain.profile import ProfileSetRequest, ProfileSettingsPatch
from dm_cli.ports.secret_store import SecretStore
from dm_client.domain.enums import SqlStatementType
from dm_client.domain.errors import (
    ConfigurationError,
    InvalidArgumentError,
    QueryError,
    QueryTimeoutError,
    UnsupportedSqlError,
)
from dm_client.domain.results import ActualPlanResult, ExecutionMetadata, PlanStatistic

if TYPE_CHECKING:
    from pathlib import Path

    from dm_cli.application.results import SqlCommandData
    from dm_client.domain.configuration import DmConnectionConfig


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


@dataclass(frozen=True, slots=True, kw_only=True)
class CollectedCall:
    """One recorded runner invocation."""

    config: DmConnectionConfig
    sql: str
    target_label: str
    timeout_seconds: float | None


def make_result() -> ActualPlanResult:
    return ActualPlanResult(
        provider="disql-autotrace",
        executed=True,
        plan_text="1   #NSET2: [8, 1, 48]\n2     #PRJT2: [8, 1, 48]",
        statistics=(
            PlanStatistic(name="logical_reads", value=4),
            PlanStatistic(name="exec_time_ms", value=2),
        ),
        statistics_text="logical reads 4\nexec time(ms) 2",
        autotrace_text="Statistics\nlogical reads 4\nexec time(ms) 2",
        duration_ms=12.5,
        metadata=ExecutionMetadata(statement_type=SqlStatementType.SELECT, duration_ms=12.5),
    )


class FakeRunner:
    """Record actual-plan calls and return a typed result or a configured error."""

    def __init__(self, *, result: ActualPlanResult | None = None, error: Exception | None = None) -> None:
        self.calls: list[CollectedCall] = []
        self.result = make_result() if result is None else result
        self.error = error

    async def collect(
        self,
        config: DmConnectionConfig,
        sql: str,
        *,
        target_label: str,
        timeout_seconds: float | None,
    ) -> ActualPlanResult:
        self.calls.append(
            CollectedCall(
                config=config,
                sql=sql,
                target_label=target_label,
                timeout_seconds=timeout_seconds,
            )
        )
        if self.error is not None:
            raise self.error
        return self.result


def make_profiles(tmp_path: Path, *, query_timeout: float = 0.0) -> ProfileService:
    profiles = ProfileService(
        JsonProfileStore(tmp_path / "profiles.json", lock_timeout=0.0),
        MemorySecretStore(),
        working_directory=tmp_path,
    )
    profiles.set(
        ProfileSetRequest(
            name=ProfileName(value="dev"),
            settings=ProfileSettingsPatch(
                host="127.0.0.1",
                port=15237,
                user="APP",
                schema="APP",
                query_timeout=query_timeout,
            ),
            password="never-print-this",
        )
    )
    return profiles


def request_for(
    sql: str,
    *,
    actual: bool = True,
    timeout_seconds: float | None = None,
) -> CommandRequest:
    return CommandRequest(
        group=CommandGroup.SQL,
        action=CommandAction.EXPLAIN,
        selected_profile=ProfileName(value="dev"),
        sql_input=SqlInputSpec.inline(sql),
        sql_timeout_seconds=timeout_seconds,
        sql_explain_actual=actual,
    )


def run(
    service: ActualPlanService,
    request: CommandRequest,
    inputs: LoadedInputs,
) -> SqlCommandData:
    return asyncio.run(service.execute(request, inputs))


def execute(
    profiles: ProfileService,
    runner: FakeRunner,
    sql: str,
    *,
    timeout_seconds: float | None = None,
) -> SqlCommandData:
    request = request_for(sql, timeout_seconds=timeout_seconds)
    return run(ActualPlanService(profiles, runner), request, load_inputs(request, stdin_text=None))


def test_execute_strips_explain_and_returns_the_actual_plan_result(tmp_path: Path) -> None:
    runner = FakeRunner()
    profiles = make_profiles(tmp_path)

    data = execute(profiles, runner, "EXPLAIN SELECT * FROM T WHERE ID = 1")

    assert isinstance(data.result, ActualPlanResult)
    assert data.status is CommandStatus.COMPLETED
    assert data.command_group is CommandGroup.SQL
    assert data.action is CommandAction.EXPLAIN
    assert data.profile == "dev"
    assert data.result is runner.result
    assert len(runner.calls) == 1
    call = runner.calls[0]
    assert call.sql == "SELECT * FROM T WHERE ID = 1"
    assert call.target_label == "dev"
    assert call.timeout_seconds is None
    assert call.config.host == "127.0.0.1"
    assert call.config.port == 15237
    assert call.config.schema is not None
    assert call.config.schema.value == "APP"


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE t SET x = 1",
        "EXPLAIN UPDATE t SET x = 1",
        "DELETE FROM t",
        "CREATE TABLE t (ID INT)",
        "SELECT * FROM t FOR UPDATE",
    ],
)
def test_rejects_non_read_only_sql_before_collecting(tmp_path: Path, sql: str) -> None:
    runner = FakeRunner()

    with pytest.raises(UnsupportedSqlError):
        execute(make_profiles(tmp_path), runner, sql)

    assert runner.calls == []


def test_rejects_explain_analyze_as_unsupported(tmp_path: Path) -> None:
    runner = FakeRunner()

    with pytest.raises(UnsupportedSqlError):
        execute(make_profiles(tmp_path), runner, "EXPLAIN ANALYZE SELECT 1 FROM DUAL")

    assert runner.calls == []


def test_requires_the_actual_flag(tmp_path: Path) -> None:
    runner = FakeRunner()
    request = request_for("SELECT 1 FROM DUAL", actual=False)

    with pytest.raises(InvalidArgumentError):
        run(ActualPlanService(make_profiles(tmp_path), runner), request, load_inputs(request, stdin_text=None))

    assert runner.calls == []


@pytest.mark.parametrize(
    ("request_timeout", "profile_timeout", "expected"),
    [
        (2.5, 7.0, 2.5),
        (None, 7.0, 7.0),
        (None, 0.0, None),
    ],
)
def test_timeout_selection(
    tmp_path: Path,
    request_timeout: float | None,
    profile_timeout: float,
    expected: float | None,
) -> None:
    runner = FakeRunner()

    execute(
        make_profiles(tmp_path, query_timeout=profile_timeout),
        runner,
        "SELECT 1 FROM DUAL",
        timeout_seconds=request_timeout,
    )

    assert runner.calls[0].timeout_seconds == expected


@pytest.mark.parametrize(
    "error",
    [
        ConfigurationError("disql executable could not be started"),
        QueryTimeoutError("disql autotrace timed out"),
        QueryError("disql autotrace failed"),
    ],
)
def test_runner_errors_propagate_unchanged(tmp_path: Path, error: Exception) -> None:
    runner = FakeRunner(error=error)

    with pytest.raises(type(error)) as caught:
        execute(make_profiles(tmp_path), runner, "SELECT 1 FROM DUAL")

    assert caught.value is error
