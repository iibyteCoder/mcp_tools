"""Unit tests for the disql autotrace actual-plan adapter."""

from __future__ import annotations

import ast
import asyncio
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import get_args

import pytest

import dm_client
import dm_client.ports as ports_package
import dm_client.ports.actual_plan as actual_plan_port
from dm_client.adapters.disql import runner as runner_module
from dm_client.adapters.disql.runner import (
    DEFAULT_ACTUAL_PLAN_TIMEOUT_SECONDS,
    DEFAULT_DISQL_EXECUTABLE,
    DISQL_AUTOTRACE_PROVIDER,
    DISQL_EXECUTABLE_ENV,
    NO_STATISTICS_MESSAGE,
    DisqlAutotraceRunner,
    _parse_autotrace,
)
from dm_client.domain.configuration import DmConnectionConfig, SecretValue
from dm_client.domain.enums import SqlStatementType
from dm_client.domain.errors import ConfigurationError, QueryError, QueryTimeoutError
from dm_client.domain.results import (
    ActualPlanResult,
    ExecutionMetadata,
    PlanStatistic,
    ResponsePayload,
    TargetMetadata,
)
from dm_client.domain.values import SchemaName
from dm_client.ports.actual_plan import ActualPlanRunner

PLAN_LINES = (
    "1   #NSET2: [8, 1, 48]",
    "2     #PRJT2: [8, 1, 48]; exp_num(1)",
)
STATISTIC_LINES = (
    "\t0\t    data pages changed",
    "\t0\t    undo pages changed",
    "\t24\t    logical reads",
    "\t2\t    physical reads",
    "\t360\t    redo size",
    "\t128\t    bytes sent to client",
    "\t64\t    bytes received from client",
    "\t3\t    roundtrips to/from client",
    "\t1\t    sorts (memory)",
    "\t0\t    sorts (disk)",
    "\t7\t    rows processed",
    "\t4\t    io wait time(ms)",
    "\t12\t    exec time(ms)",
)
EXPECTED_STATISTICS = (
    ("data_pages_changed", 0),
    ("undo_pages_changed", 0),
    ("logical_reads", 24),
    ("physical_reads", 2),
    ("redo_size", 360),
    ("bytes_sent_to_client", 128),
    ("bytes_received_from_client", 64),
    ("roundtrips_to_from_client", 3),
    ("sorts_memory", 1),
    ("sorts_disk", 0),
    ("rows_processed", 7),
    ("io_wait_time_ms", 4),
    ("exec_time_ms", 12),
)
AUTOTRACE_OUTPUT = "\n".join((*PLAN_LINES, "", "Statistics", "", *STATISTIC_LINES))
PASSWORD = "s3cret"


def make_config(*, schema: bool = True) -> DmConnectionConfig:
    return DmConnectionConfig(
        host="127.0.0.1",
        port=15237,
        user="APP",
        password=SecretValue(_value=PASSWORD),
        schema=SchemaName(value="APP") if schema else None,
    )


class FakeProcess:
    """Minimal asyncio subprocess surface used by the runner."""

    def __init__(
        self,
        *,
        stdout: bytes = b"",
        stderr: bytes = b"",
        returncode: int = 0,
        hang: bool = False,
    ) -> None:
        self._stdout = stdout
        self._stderr = stderr
        self._exit_code = returncode
        self._hang = hang
        self.returncode: int | None = None
        self.received_input: bytes | None = None
        self.killed = False
        self.waited = False

    async def communicate(self, input: bytes | None = None) -> tuple[bytes, bytes]:
        self.received_input = input
        if self._hang:
            await asyncio.sleep(3600)
        self.returncode = self._exit_code
        return self._stdout, self._stderr

    def kill(self) -> None:
        self.killed = True

    async def wait(self) -> int:
        self.waited = True
        if self.returncode is None:
            self.returncode = -9
        return self.returncode


CreateCall = tuple[tuple[object, ...], dict[str, object]]


def install_process(monkeypatch: pytest.MonkeyPatch, process: FakeProcess) -> list[CreateCall]:
    calls: list[CreateCall] = []

    async def fake_create_subprocess_exec(*args: object, **kwargs: object) -> FakeProcess:
        calls.append((args, kwargs))
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    return calls


def make_actual_result() -> ActualPlanResult:
    return ActualPlanResult(
        provider=DISQL_AUTOTRACE_PROVIDER,
        executed=True,
        plan_text="1   #NSET2: [8, 1, 48]",
        statistics=(PlanStatistic(name="logical_reads", value=24),),
        statistics_text="24 logical reads",
        autotrace_text="plan\nStatistics\n24 logical reads",
        duration_ms=1.5,
        metadata=ExecutionMetadata(
            statement_type=SqlStatementType.SELECT,
            duration_ms=1.5,
        ),
    )


def test_parse_autotrace_splits_the_estimated_plan_and_actual_statistics() -> None:
    parsed = _parse_autotrace(AUTOTRACE_OUTPUT)

    assert parsed.plan_text == "\n".join(PLAN_LINES)
    assert parsed.statistics_text == "\n".join(STATISTIC_LINES)
    assert parsed.autotrace_text == AUTOTRACE_OUTPUT.strip()
    assert [(statistic.name, statistic.value) for statistic in parsed.statistics] == list(EXPECTED_STATISTICS)


def test_parse_autotrace_ignores_disql_command_responses_in_plan_text() -> None:
    stdout = "\n".join(
        (
            "executed successfully",
            "used time: 12.345(ms)",
            "",
            *PLAN_LINES,
            "",
            "Statistics",
            "",
            *STATISTIC_LINES,
        )
    )

    parsed = _parse_autotrace(stdout)

    assert parsed.plan_text == "\n".join(PLAN_LINES)
    assert "executed successfully" in parsed.autotrace_text
    assert "used time: 12.345(ms)" in parsed.autotrace_text
    assert [(statistic.name, statistic.value) for statistic in parsed.statistics] == list(EXPECTED_STATISTICS)


def test_parse_autotrace_slugifies_unknown_labels_and_ignores_noise() -> None:
    stdout = "\n".join(
        (
            "1   #NSET2: [1, 1, 1]",
            "Statistics",
            "",
            "\t5\t    buffers pinned (count)",
            "\tignored non-numeric line",
            "noise",
        )
    )

    parsed = _parse_autotrace(stdout)

    assert parsed.plan_text == "1   #NSET2: [1, 1, 1]"
    assert [(statistic.name, statistic.value) for statistic in parsed.statistics] == [("buffers_pinned_count", 5)]
    assert parsed.statistics_text == "\n".join(
        ("\t5\t    buffers pinned (count)", "\tignored non-numeric line", "noise")
    )


def test_parse_autotrace_requires_a_statistics_section() -> None:
    with pytest.raises(QueryError, match=NO_STATISTICS_MESSAGE):
        _parse_autotrace("1   #NSET2: [1, 1, 1]")


@pytest.mark.asyncio
async def test_collect_builds_the_stdin_script_without_credentials_in_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = FakeProcess(stdout=AUTOTRACE_OUTPUT.encode("utf-8"))
    calls = install_process(monkeypatch, process)

    result = await DisqlAutotraceRunner(executable="disql-test").collect(
        make_config(),
        "SELECT 1 FROM DUAL",
        target_label="lot-01",
        timeout_seconds=5.0,
    )

    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args == ("disql-test", "-S", "/NOLOG")
    assert "s3cret" not in repr(args)
    assert kwargs["stdin"] is asyncio.subprocess.PIPE
    assert kwargs["stdout"] is asyncio.subprocess.PIPE
    assert kwargs["stderr"] is asyncio.subprocess.PIPE
    assert process.received_input is not None
    assert process.received_input.decode("utf-8").splitlines() == [
        "CONN APP/s3cret@127.0.0.1:15237",
        'SET SCHEMA "APP";',
        "SET AUTOTRACE TRACEONLY",
        "SELECT 1 FROM DUAL;",
        "EXIT",
    ]
    assert result.provider == DISQL_AUTOTRACE_PROVIDER
    assert result.executed is True
    assert result.plan_text == "\n".join(PLAN_LINES)
    assert result.statistics_text == "\n".join(STATISTIC_LINES)
    assert result.autotrace_text == AUTOTRACE_OUTPUT.strip()
    assert [(statistic.name, statistic.value) for statistic in result.statistics] == list(EXPECTED_STATISTICS)
    assert result.metadata.statement_type is SqlStatementType.SELECT
    assert result.metadata.target == TargetMetadata(
        label="lot-01",
        host="127.0.0.1",
        port=15237,
        schema="APP",
        server_version=None,
    )
    assert result.metadata.started_at is not None
    assert result.duration_ms >= 0.0


@pytest.mark.asyncio
async def test_collect_does_not_duplicate_a_terminal_semicolon(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = FakeProcess(stdout=AUTOTRACE_OUTPUT.encode("utf-8"))
    install_process(monkeypatch, process)

    result = await DisqlAutotraceRunner(executable="disql-test").collect(
        make_config(schema=False),
        "SELECT 1 FROM DUAL;",
        target_label="lot-01",
        timeout_seconds=5.0,
    )

    assert process.received_input is not None
    script = process.received_input.decode("utf-8")
    assert 'SET SCHEMA "' not in script
    assert "SELECT 1 FROM DUAL;" in script
    assert "SELECT 1 FROM DUAL;;" not in script
    assert result.metadata.target == TargetMetadata(
        label="lot-01",
        host="127.0.0.1",
        port=15237,
        schema=None,
        server_version=None,
    )


@pytest.mark.asyncio
async def test_collect_quotes_and_escapes_the_configured_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = FakeProcess(stdout=AUTOTRACE_OUTPUT.encode("utf-8"))
    install_process(monkeypatch, process)
    config = DmConnectionConfig(
        host="127.0.0.1",
        port=15237,
        user="APP",
        password=SecretValue(_value=PASSWORD),
        schema=SchemaName(value='APP"X'),
    )

    await DisqlAutotraceRunner(executable="disql-test").collect(
        config,
        "SELECT 1 FROM DUAL",
        target_label="lot-01",
        timeout_seconds=5.0,
    )

    assert process.received_input is not None
    assert 'SET SCHEMA "APP""X";' in process.received_input.decode("utf-8").splitlines()


@pytest.mark.asyncio
async def test_collect_redacts_the_password_from_autotrace_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = FakeProcess(stdout=f"{PASSWORD}\n{AUTOTRACE_OUTPUT}".encode())
    install_process(monkeypatch, process)

    result = await DisqlAutotraceRunner(executable="disql-test").collect(
        make_config(),
        "SELECT 1 FROM DUAL",
        target_label="lot-01",
        timeout_seconds=5.0,
    )

    assert PASSWORD not in result.autotrace_text
    assert "<redacted>" in result.autotrace_text


@pytest.mark.asyncio
async def test_collect_uses_the_environment_executable_when_none_is_given(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = FakeProcess(stdout=AUTOTRACE_OUTPUT.encode("utf-8"))
    calls = install_process(monkeypatch, process)
    monkeypatch.setenv(DISQL_EXECUTABLE_ENV, "/opt/dm/disql")

    await DisqlAutotraceRunner().collect(
        make_config(),
        "SELECT 1 FROM DUAL",
        target_label="lot-01",
        timeout_seconds=5.0,
    )

    assert calls[0][0][0] == "/opt/dm/disql"


@pytest.mark.asyncio
async def test_collect_falls_back_to_disql_on_path(monkeypatch: pytest.MonkeyPatch) -> None:
    process = FakeProcess(stdout=AUTOTRACE_OUTPUT.encode("utf-8"))
    calls = install_process(monkeypatch, process)
    monkeypatch.delenv(DISQL_EXECUTABLE_ENV, raising=False)

    await DisqlAutotraceRunner().collect(
        make_config(),
        "SELECT 1 FROM DUAL",
        target_label="lot-01",
        timeout_seconds=5.0,
    )

    assert calls[0][0][0] == DEFAULT_DISQL_EXECUTABLE == "disql"


@pytest.mark.asyncio
@pytest.mark.parametrize("timeout", [None, 0.0])
async def test_collect_uses_the_default_timeout_for_missing_or_non_positive_values(
    monkeypatch: pytest.MonkeyPatch, timeout: float | None
) -> None:
    process = FakeProcess(hang=True)
    install_process(monkeypatch, process)
    monkeypatch.setattr(runner_module, "DEFAULT_ACTUAL_PLAN_TIMEOUT_SECONDS", 0.01)

    with pytest.raises(QueryTimeoutError):
        await DisqlAutotraceRunner(executable="disql-test").collect(
            make_config(),
            "SELECT 1 FROM DUAL",
            target_label="lot-01",
            timeout_seconds=timeout,
        )

    assert process.killed is True
    assert process.waited is True


@pytest.mark.asyncio
async def test_collect_kills_and_waits_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    process = FakeProcess(hang=True)
    install_process(monkeypatch, process)

    with pytest.raises(QueryTimeoutError, match="timed out"):
        await DisqlAutotraceRunner(executable="disql-test").collect(
            make_config(),
            "SELECT 1 FROM DUAL",
            target_label="lot-01",
            timeout_seconds=0.01,
        )

    assert process.killed is True
    assert process.waited is True


@pytest.mark.asyncio
async def test_collect_reports_nonzero_exit_with_redacted_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = FakeProcess(
        stdout=b"partial output",
        stderr=f"login failed for password {PASSWORD}".encode(),
        returncode=2,
    )
    install_process(monkeypatch, process)

    with pytest.raises(QueryError) as excinfo:
        await DisqlAutotraceRunner(executable="disql-test").collect(
            make_config(),
            "SELECT 1 FROM DUAL",
            target_label="lot-01",
            timeout_seconds=5.0,
        )

    message = str(excinfo.value)
    assert "exit code 2" in message
    assert PASSWORD not in message
    assert "<redacted>" in message


@pytest.mark.asyncio
async def test_collect_wraps_a_missing_executable_as_configuration_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_create_subprocess_exec(*args: object, **kwargs: object) -> FakeProcess:
        raise FileNotFoundError("disql")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    with pytest.raises(ConfigurationError) as excinfo:
        await DisqlAutotraceRunner(executable="missing-disql").collect(
            make_config(),
            "SELECT 1 FROM DUAL",
            target_label="lot-01",
            timeout_seconds=5.0,
        )

    assert excinfo.value.hint is not None
    assert DISQL_EXECUTABLE_ENV in excinfo.value.hint


@pytest.mark.asyncio
async def test_collect_requires_a_statistics_section(monkeypatch: pytest.MonkeyPatch) -> None:
    process = FakeProcess(stdout=b"1   #NSET2: [8, 1, 48]\n")
    install_process(monkeypatch, process)

    with pytest.raises(QueryError, match=NO_STATISTICS_MESSAGE):
        await DisqlAutotraceRunner(executable="disql-test").collect(
            make_config(),
            "SELECT 1 FROM DUAL",
            target_label="lot-01",
            timeout_seconds=5.0,
        )


def test_actual_plan_result_is_frozen_slots_kw_only_and_exported() -> None:
    result = make_actual_result()

    assert result.provider == "disql-autotrace"
    assert result.executed is True
    assert result.statistics[0].name == "logical_reads"
    assert not hasattr(result, "__dict__")
    with pytest.raises(FrozenInstanceError):
        result.plan_text = "changed"  # type: ignore[misc]
    with pytest.raises(TypeError):
        ActualPlanResult("provider", True)  # type: ignore[misc]

    assert dm_client.ActualPlanResult is ActualPlanResult
    assert dm_client.PlanStatistic is PlanStatistic
    assert dm_client.ActualPlanRunner is ActualPlanRunner
    assert dm_client.DisqlAutotraceRunner is DisqlAutotraceRunner
    assert dm_client.DEFAULT_ACTUAL_PLAN_TIMEOUT_SECONDS == DEFAULT_ACTUAL_PLAN_TIMEOUT_SECONDS
    assert ActualPlanResult in get_args(ResponsePayload)


def test_ports_expose_the_protocol_but_not_the_concrete_disql_runner() -> None:
    assert actual_plan_port.ActualPlanRunner is ActualPlanRunner
    assert hasattr(ports_package, "ActualPlanRunner")
    assert not hasattr(ports_package, "DisqlAutotraceRunner")
    assert not hasattr(actual_plan_port, "DisqlAutotraceRunner")


def test_disql_runner_does_not_import_driver_specific_or_cli_modules() -> None:
    source_path = Path(runner_module.__file__ or "")
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.append(node.module)

    assert all(module.split(".")[0] not in {"dmPython", "dm_cli", "click"} for module in modules)
