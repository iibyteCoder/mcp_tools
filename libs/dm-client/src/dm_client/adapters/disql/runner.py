"""disql ``SET AUTOTRACE TRACEONLY`` adapter for actual aggregate plans.

The plan text is the estimated optimizer plan. The ``Statistics`` block is
actual aggregate runtime data and does not contain per-operator timings or
loop counts.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Final

from dm_client.domain.enums import SqlStatementType
from dm_client.domain.errors import ConfigurationError, QueryError, QueryTimeoutError
from dm_client.domain.results import ActualPlanResult, PlanStatistic, TargetMetadata
from dm_client.execution.tabular import build_metadata

if TYPE_CHECKING:
    from dm_client.domain.configuration import DmConnectionConfig

DISQL_EXECUTABLE_ENV: Final[str] = "DB_DM_DISQL_PATH"
DEFAULT_DISQL_EXECUTABLE: Final[str] = "disql"
DISQL_AUTOTRACE_PROVIDER: Final[str] = "disql-autotrace"
DEFAULT_ACTUAL_PLAN_TIMEOUT_SECONDS: Final[float] = 60.0
REDACTED_SECRET_TEXT: Final[str] = "<redacted>"
NO_STATISTICS_MESSAGE: Final[str] = "disql autotrace did not return a Statistics section"

_STATISTICS_HEADER: Final[str] = "statistics"
_PLAN_LINE_PATTERN: Final[re.Pattern[str]] = re.compile(r"^\s*\d+\s+#")
_STATISTIC_LINE_PATTERN: Final[re.Pattern[str]] = re.compile(r"^\s*(?P<value>\d+)\s+(?P<label>\S.*?)\s*$")
_NON_NAME_PATTERN: Final[re.Pattern[str]] = re.compile(r"[^a-z0-9]+")
_MAX_DIAGNOSTIC_LENGTH: Final[int] = 500
_STATISTIC_NAMES: Final[dict[str, str]] = {
    "data pages changed": "data_pages_changed",
    "undo pages changed": "undo_pages_changed",
    "logical reads": "logical_reads",
    "physical reads": "physical_reads",
    "redo size": "redo_size",
    "bytes sent to client": "bytes_sent_to_client",
    "bytes received from client": "bytes_received_from_client",
    "roundtrips to/from client": "roundtrips_to_from_client",
    "sorts (memory)": "sorts_memory",
    "sorts (disk)": "sorts_disk",
    "rows processed": "rows_processed",
    "io wait time(ms)": "io_wait_time_ms",
    "exec time(ms)": "exec_time_ms",
}


@dataclass(frozen=True, slots=True, kw_only=True)
class ParsedAutotrace:
    """Typed split of autotrace stdout into plan and actual statistics."""

    plan_text: str
    statistics: tuple[PlanStatistic, ...]
    statistics_text: str
    autotrace_text: str


class DisqlAutotraceRunner:
    """Collect one estimated plan and actual aggregate statistics through disql."""

    def __init__(self, executable: str | None = None) -> None:
        self._executable = _resolve_executable(executable)

    async def collect(
        self,
        config: DmConnectionConfig,
        sql: str,
        *,
        target_label: str,
        timeout_seconds: float | None,
    ) -> ActualPlanResult:
        """Run ``sql`` with autotrace trace-only mode and parse its output."""

        timeout = _resolve_timeout(timeout_seconds)
        script = _build_script(config, sql)
        secret = config.password.reveal()
        started_at = datetime.now(timezone.utc)
        started = time.perf_counter()
        try:
            process = await asyncio.create_subprocess_exec(
                self._executable,
                "-S",
                "/NOLOG",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            raise ConfigurationError(
                "disql executable could not be started",
                hint=f"set {DISQL_EXECUTABLE_ENV} to the disql executable path",
            ) from exc

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(input=script.encode("utf-8")),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                process.kill()
            await process.wait()
            raise QueryTimeoutError(f"disql autotrace timed out after {timeout:g} seconds") from None

        duration_ms = (time.perf_counter() - started) * 1000
        stdout = _redact(_decode(stdout_bytes), secret)
        stderr = _redact(_decode(stderr_bytes), secret)
        if process.returncode != 0:
            raise QueryError(_failure_message(process.returncode, stdout, stderr))

        parsed = _parse_autotrace(stdout)
        target = TargetMetadata(
            label=target_label,
            host=config.host,
            port=config.port,
            schema=config.schema.value if config.schema is not None else None,
            server_version=None,
        )
        metadata = build_metadata(SqlStatementType.SELECT, started_at, target)
        return ActualPlanResult(
            provider=DISQL_AUTOTRACE_PROVIDER,
            executed=True,
            plan_text=parsed.plan_text,
            statistics=parsed.statistics,
            statistics_text=parsed.statistics_text,
            autotrace_text=parsed.autotrace_text,
            duration_ms=duration_ms,
            metadata=metadata,
        )


def _resolve_executable(executable: str | None) -> str:
    """Resolve the disql executable from the caller, environment or PATH."""

    if executable is not None and executable.strip():
        return executable
    configured = os.environ.get(DISQL_EXECUTABLE_ENV)
    if configured is not None and configured.strip():
        return configured
    return DEFAULT_DISQL_EXECUTABLE


def _resolve_timeout(timeout_seconds: float | None) -> float:
    """Use the default deadline when no positive timeout was supplied."""

    if timeout_seconds is None or timeout_seconds <= 0:
        return DEFAULT_ACTUAL_PLAN_TIMEOUT_SECONDS
    return timeout_seconds


def _build_script(config: DmConnectionConfig, sql: str) -> str:
    """Build the stdin script without ever putting credentials in arguments."""

    statement = sql if sql.rstrip().endswith(";") else f"{sql};"
    connection = f"CONN {config.user}/{config.password.reveal()}@{config.host}:{config.port}"
    lines = [connection]
    if config.schema is not None:
        schema_identifier = config.schema.value.replace('"', '""')
        lines.append(f'SET SCHEMA "{schema_identifier}";')
    lines.extend(("SET AUTOTRACE TRACEONLY", statement, "EXIT", ""))
    return "\n".join(lines)


def _decode(value: bytes | None) -> str:
    """Decode subprocess output without failing on invalid byte sequences."""

    if not value:
        return ""
    return value.decode("utf-8", errors="replace")


def _redact(text: str, secret: str) -> str:
    """Remove the configured password from any process output."""

    if not secret:
        return text
    return text.replace(secret, REDACTED_SECRET_TEXT)


def _failure_message(exit_code: int | None, stdout: str, stderr: str) -> str:
    """Build a bounded, already-sanitized diagnostic for a failed process."""

    parts = [f"disql autotrace failed with exit code {exit_code}"]
    if stderr.strip():
        parts.append(f"stderr: {_truncate(stderr.strip())}")
    if stdout.strip():
        parts.append(f"stdout: {_truncate(stdout.strip())}")
    return "; ".join(parts)


def _truncate(text: str) -> str:
    """Bound diagnostic excerpts returned to callers."""

    if len(text) <= _MAX_DIAGNOSTIC_LENGTH:
        return text
    return f"{text[:_MAX_DIAGNOSTIC_LENGTH]}..."


def _parse_autotrace(stdout: str) -> ParsedAutotrace:
    """Split autotrace output and parse the actual aggregate statistics."""

    autotrace_text = stdout.strip()
    lines = autotrace_text.splitlines()
    header_index = next(
        (index for index, line in enumerate(lines) if line.strip().lower() == _STATISTICS_HEADER),
        None,
    )
    if header_index is None:
        raise QueryError(NO_STATISTICS_MESSAGE)
    plan_text = "\n".join(line for line in lines[:header_index] if _PLAN_LINE_PATTERN.match(line) is not None)
    statistics_text = _trim_blank_lines("\n".join(lines[header_index + 1 :]))
    return ParsedAutotrace(
        plan_text=plan_text,
        statistics=_parse_statistics(statistics_text),
        statistics_text=statistics_text,
        autotrace_text=autotrace_text,
    )


def _trim_blank_lines(text: str) -> str:
    """Strip surrounding blank lines while preserving line indentation."""

    lines = text.splitlines()
    start = 0
    end = len(lines)
    while start < end and not lines[start].strip():
        start += 1
    while end > start and not lines[end - 1].strip():
        end -= 1
    return "\n".join(lines[start:end])


def _parse_statistics(statistics_text: str) -> tuple[PlanStatistic, ...]:
    """Convert numeric statistic lines into normalized typed entries."""

    statistics: list[PlanStatistic] = []
    for line in statistics_text.splitlines():
        match = _STATISTIC_LINE_PATTERN.match(line)
        if match is None:
            continue
        label = " ".join(match.group("label").split()).lower()
        name = _STATISTIC_NAMES.get(label) or _slugify(label)
        if not name:
            continue
        statistics.append(PlanStatistic(name=name, value=int(match.group("value"))))
    return tuple(statistics)


def _slugify(label: str) -> str:
    """Reduce an unknown statistic label to ``[a-z0-9_]+``."""

    return _NON_NAME_PATTERN.sub("_", label).strip("_")


__all__ = [
    "DEFAULT_ACTUAL_PLAN_TIMEOUT_SECONDS",
    "DEFAULT_DISQL_EXECUTABLE",
    "DISQL_AUTOTRACE_PROVIDER",
    "DISQL_EXECUTABLE_ENV",
    "NO_STATISTICS_MESSAGE",
    "DisqlAutotraceRunner",
    "ParsedAutotrace",
]
