"""Unit tests for the schema maintenance application service and runner dispatch."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

import pytest

from db_cli_kit.profiles import ProfileName
from dm_cli.adapters.profile_store import JsonProfileStore
from dm_cli.application.profile import ProfileService, ProfileServiceError, ProfileServiceErrorCode
from dm_cli.application.results import InspectionCommandData
from dm_cli.application.runner import CliRuntime, execute_request
from dm_cli.application.schema_maintenance import SchemaMaintenanceService
from dm_cli.domain.command import CommandAction, CommandGroup, CommandRequest, CommandStatus
from dm_cli.domain.profile import ProfileSetRequest, ProfileSettingsPatch
from dm_cli.ports.secret_store import SecretStore
from dm_client.domain.enums import SqlStatementType, WriteOutcome
from dm_client.domain.errors import InvalidArgumentError
from dm_client.domain.results import (
    AnalyzeOptions,
    AnalyzeResult,
    AnalyzeStatistics,
    ExecutionMetadata,
)
from dm_client.domain.values import SchemaName, TableName
from dm_client.ports.driver import DriverColumn
from dm_client.sql.analyze_queries import GATHER_TABLE_STATS_CALL

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from dm_client.domain.configuration import DmConnectionConfig
    from dm_client.domain.values import DatabaseValue

STATISTICS_COLUMNS = (
    DriverColumn(name="NUM_ROWS", type_name="NUMBER"),
    DriverColumn(name="LAST_ANALYZED", type_name="TIMESTAMP"),
)


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


@dataclass(frozen=True)
class QueryFixture:
    columns: tuple[DriverColumn, ...]
    rows: tuple[tuple[DatabaseValue, ...], ...]


def empty_statistics() -> QueryFixture:
    return QueryFixture(columns=STATISTICS_COLUMNS, rows=())


def statistics_fixture(num_rows: int, last_analyzed: datetime) -> QueryFixture:
    return QueryFixture(columns=STATISTICS_COLUMNS, rows=((num_rows, last_analyzed),))


class MaintenanceCursor:
    def __init__(self, connection: FakeConnection) -> None:
        self._connection = connection
        self._description: Sequence[DriverColumn] | None = None
        self._rows: list[tuple[DatabaseValue, ...]] = []

    @property
    def description(self) -> Sequence[DriverColumn] | None:
        return self._description

    @property
    def rowcount(self) -> int:
        return 0

    def execute(self, sql: str, parameters: tuple[object, ...] = ()) -> None:
        self._connection.executed.append((sql, tuple(parameters)))
        if "CALL DBMS_STATS" in sql:
            self._description = None
            self._rows = []
            return
        fixture = self._connection.next_statistics()
        self._description = fixture.columns
        self._rows = list(fixture.rows)

    def fetchmany(self, size: int) -> Sequence[Sequence[object]]:
        batch = self._rows[:size]
        self._rows = self._rows[size:]
        return batch

    def close(self) -> None:
        return None


class FakeConnection:
    user = "APP"
    server_version = "8.1.4.80"
    str_case_sensitive = False
    max_identifier_length = 128

    def __init__(self, statistics: tuple[QueryFixture, ...] = ()) -> None:
        self.current_schema = "APP"
        self.statistics = list(statistics)
        self.executed: list[tuple[str, tuple[object, ...]]] = []
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def next_statistics(self) -> QueryFixture:
        if not self.statistics:
            return empty_statistics()
        return self.statistics.pop(0)

    def cursor(self) -> MaintenanceCursor:
        return MaintenanceCursor(self)

    def explain(self, sql: str) -> str:
        return f"plan for {sql}"

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closed = True


class FakeFactory:
    def __init__(self, connection: FakeConnection) -> None:
        self._connection = connection
        self.configs: list[DmConnectionConfig] = []

    def connect(self, config: DmConnectionConfig) -> FakeConnection:
        self.configs.append(config)
        if config.schema is not None:
            self._connection.current_schema = config.schema.value
        return self._connection


def make_profiles(tmp_path: Path) -> ProfileService:
    profiles = ProfileService(
        JsonProfileStore(tmp_path / "profiles.json", lock_timeout=0.0),
        MemorySecretStore(),
        working_directory=tmp_path,
    )
    profiles.set(
        ProfileSetRequest(
            name=ProfileName(value="dev"),
            settings=ProfileSettingsPatch(host="127.0.0.1", port=15237, user="APP", schema="APP"),
            password="never-print-this",
        )
    )
    return profiles


def maintenance_service(
    tmp_path: Path,
    statistics: tuple[QueryFixture, ...] = (),
) -> tuple[SchemaMaintenanceService, FakeFactory, FakeConnection]:
    profiles = make_profiles(tmp_path)
    connection = FakeConnection(statistics)
    factory = FakeFactory(connection)
    return SchemaMaintenanceService(profiles, factory), factory, connection


def request_for(
    action: CommandAction = CommandAction.ANALYZE,
    *,
    schema: SchemaName | None = None,
    table: TableName | None = None,
    partition: str | None = None,
    estimate_percent: float | None = None,
    cascade: bool | None = None,
    degree: int | None = None,
    profile: str = "dev",
) -> CommandRequest:
    return CommandRequest(
        group=CommandGroup.SCHEMA,
        action=action,
        selected_profile=ProfileName(value=profile),
        schema_name=schema,
        schema_table=table,
        schema_partition=partition,
        schema_estimate_percent=estimate_percent,
        schema_cascade=cascade,
        schema_degree=degree,
    )


def test_schema_analyze_service_dispatches_options_and_returns_the_analysis(tmp_path: Path) -> None:
    analyzed_at = datetime(2026, 11, 8, 18, 30)
    service, factory, connection = maintenance_service(
        tmp_path,
        (empty_statistics(), statistics_fixture(3, analyzed_at)),
    )

    data = asyncio.run(
        service.execute(
            request_for(
                table=TableName(value="T"),
                partition="P1",
                estimate_percent=10.0,
                cascade=False,
                degree=4,
            )
        )
    )

    assert isinstance(data, InspectionCommandData)
    assert isinstance(data.result, AnalyzeResult)
    assert data.command_group is CommandGroup.SCHEMA
    assert data.action is CommandAction.ANALYZE
    assert data.profile == "dev"
    assert data.result.schema == "APP"
    assert data.result.table == "T"
    assert data.result.partition == "P1"
    assert data.result.options == AnalyzeOptions(estimate_percent=10.0, cascade=False, degree=4)
    assert data.result.before == AnalyzeStatistics()
    assert data.result.after == AnalyzeStatistics(last_analyzed=analyzed_at, num_rows=3)
    assert data.result.outcome is WriteOutcome.COMMITTED
    assert factory.configs[0].schema == SchemaName(value="APP")
    assert connection.commits == 1
    assert connection.executed[1] == (
        GATHER_TABLE_STATS_CALL,
        ("APP", "T", "P1", 10.0, False, None, 4, None, False),
    )


def test_schema_analyze_service_binds_an_explicit_schema(tmp_path: Path) -> None:
    service, factory, connection = maintenance_service(tmp_path)

    data = asyncio.run(
        service.execute(
            request_for(schema=SchemaName(value="OTHER"), table=TableName(value="T"))
        )
    )

    assert isinstance(data.result, AnalyzeResult)
    assert data.result.schema == "OTHER"
    assert factory.configs[0].schema == SchemaName(value="APP")
    assert connection.executed[1][1] == ("OTHER", "T", None, None, False, None, None, None, True)


def test_schema_analyze_service_defaults_cascade_to_true_when_unset(tmp_path: Path) -> None:
    service, _, connection = maintenance_service(tmp_path)

    data = asyncio.run(service.execute(request_for(table=TableName(value="T"))))

    assert isinstance(data.result, AnalyzeResult)
    assert data.result.options.cascade is True
    assert connection.executed[1][1][-1] is True


def test_schema_analyze_service_requires_a_table_before_connecting(tmp_path: Path) -> None:
    service, factory, connection = maintenance_service(tmp_path)

    with pytest.raises(InvalidArgumentError, match="--table"):
        asyncio.run(service.execute(request_for()))

    assert factory.configs == []
    assert connection.executed == []


def test_schema_analyze_service_rejects_other_schema_actions(tmp_path: Path) -> None:
    service, factory, _ = maintenance_service(tmp_path)

    with pytest.raises(InvalidArgumentError):
        asyncio.run(service.execute(request_for(CommandAction.STATS, table=TableName(value="T"))))

    assert factory.configs == []


def test_schema_analyze_service_reports_a_missing_profile(tmp_path: Path) -> None:
    service, factory, _ = maintenance_service(tmp_path)

    with pytest.raises(ProfileServiceError) as caught:
        asyncio.run(service.execute(request_for(table=TableName(value="T"), profile="missing")))

    assert caught.value.code is ProfileServiceErrorCode.NOT_FOUND
    assert factory.configs == []


class RecordingExecutor:
    """Record which application service the runner dispatched to."""

    def __init__(self) -> None:
        self.calls: list[CommandRequest] = []

    async def execute(self, request: CommandRequest) -> InspectionCommandData:
        self.calls.append(request)
        return InspectionCommandData(
            status=CommandStatus.COMPLETED,
            command_group=request.group,
            action=request.action,
            profile="dev",
            result=AnalyzeResult(
                schema="APP",
                table="T",
                partition=None,
                options=AnalyzeOptions(),
                before=AnalyzeStatistics(),
                after=AnalyzeStatistics(),
                outcome=WriteOutcome.COMMITTED,
                duration_ms=0.0,
                metadata=ExecutionMetadata(statement_type=SqlStatementType.CALL, duration_ms=0.0),
            ),
        )


def test_runner_dispatches_analyze_to_the_maintenance_service(tmp_path: Path) -> None:
    profiles = make_profiles(tmp_path)
    maintenance = RecordingExecutor()
    inspection = RecordingExecutor()
    runtime = CliRuntime(
        profile_service=profiles,
        schema_inspection_service=inspection,
        schema_maintenance_service=maintenance,
    )

    asyncio.run(
        execute_request(
            runtime,
            request_for(table=TableName(value="T")),
            stdin_text=None,
        )
    )

    assert [call.action for call in maintenance.calls] == [CommandAction.ANALYZE]
    assert inspection.calls == []
