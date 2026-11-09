"""Application service for executed read-only plans through disql autotrace."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from dm_cli.application.errors import CliFailure, ErrorDetail
from dm_cli.application.input import SQL_INPUT_ARGUMENT
from dm_cli.application.results import SqlCommandData
from dm_cli.domain.command import (
    CommandAction,
    CommandGroup,
    CommandRequest,
    CommandStatus,
    DiagnosticErrorType,
    ErrorCode,
    ExitCode,
)
from dm_client import (
    ClientError,
    DmSqlParser,
    ExecutionPolicy,
    InvalidArgumentError,
    ParsedSql,
    SqlInput,
    SqlParseError,
    UnsupportedSqlError,
    strip_explain_prefix,
    validate_execution_policy,
)

if TYPE_CHECKING:
    from dm_cli.application.input import LoadedInputs
    from dm_cli.application.profile import ProfileService
    from dm_cli.domain.command import SqlInputSpec
    from dm_cli.domain.profile import ProfileRecord
    from dm_client import ActualPlanRunner

_ACTUAL_FLAG_MESSAGE: Final[str] = "actual plan requires --actual"
_EXPLAIN_ACTION_MESSAGE: Final[str] = "actual plan requires the sql explain action"
_EXPLAIN_ANALYZE_MESSAGE: Final[str] = "EXPLAIN ANALYZE is not supported"
_EXPLAIN_ANALYZE_HINT: Final[str] = "remove ANALYZE from the EXPLAIN statement"
_MISSING_SQL_MESSAGE: Final[str] = "SQL input is required"


class ActualPlanService:
    """Collect one estimated plan with actual aggregate statistics through disql."""

    def __init__(self, profiles: ProfileService, runner: ActualPlanRunner) -> None:
        self._profiles = profiles
        self._runner = runner

    async def execute(self, request: CommandRequest, inputs: LoadedInputs) -> SqlCommandData:
        """Execute one read-only SQL statement through autotrace and return its result."""

        if request.group is not CommandGroup.SQL or request.action is not CommandAction.EXPLAIN:
            raise InvalidArgumentError(_EXPLAIN_ACTION_MESSAGE)
        if not request.sql_explain_actual:
            raise InvalidArgumentError(_ACTUAL_FLAG_MESSAGE)
        sql = inputs.sql
        if sql is None:
            raise InvalidArgumentError(_MISSING_SQL_MESSAGE)

        inner = parse_read_only_actual_plan(sql)
        selection = self._profiles.selection(request.selected_profile)
        profile = selection.profile
        config = self._profiles.connection_config(profile)
        result = await self._runner.collect(
            config,
            str(inner.normalized_sql),
            target_label=profile.name.value,
            timeout_seconds=_effective_timeout(request, profile),
        )
        return SqlCommandData(
            status=CommandStatus.COMPLETED,
            command_group=request.group,
            action=request.action,
            profile=profile.name.value,
            result=result,
        )


def parse_read_only_actual_plan(sql: SqlInput) -> ParsedSql:
    """Parse ``sql`` for actual execution and require a read-only statement."""

    parser = DmSqlParser()
    original = str(sql.text)
    parsed = parser.parse(original)
    if parsed.is_explain_analyze:
        raise UnsupportedSqlError(_EXPLAIN_ANALYZE_MESSAGE, hint=_EXPLAIN_ANALYZE_HINT)
    inner = strip_explain_prefix(original)
    if not str(inner).strip():
        raise InvalidArgumentError(_MISSING_SQL_MESSAGE)
    inner_parsed = parser.parse(inner)
    validate_execution_policy(inner_parsed, ExecutionPolicy.READ_ONLY)
    return inner_parsed


def actual_plan_diagnostic_sql(request: CommandRequest, sql: SqlInput) -> ParsedSql:
    """Parse actual-plan SQL locally and map client failures to CLI diagnostics."""

    try:
        return parse_read_only_actual_plan(sql)
    except (SqlParseError, InvalidArgumentError, UnsupportedSqlError) as exc:
        raise _diagnostic_failure(exc, request.sql_input) from exc


def _diagnostic_failure(exc: ClientError, input_spec: SqlInputSpec | None) -> CliFailure:
    code, error_type = _diagnostic_kind(exc)
    return CliFailure(
        code=code,
        message=exc.message,
        retryable=False,
        details=(
            ErrorDetail(
                error_type=error_type,
                argument=SQL_INPUT_ARGUMENT,
                source=input_spec.source if input_spec is not None else None,
            ),
        ),
        exit_code=ExitCode.INVALID_ARGUMENT,
    )


def _diagnostic_kind(exc: ClientError) -> tuple[ErrorCode, DiagnosticErrorType]:
    if isinstance(exc, SqlParseError):
        return ErrorCode.INVALID_SQL, DiagnosticErrorType.SQL_PARSE
    if isinstance(exc, UnsupportedSqlError):
        return ErrorCode.UNSUPPORTED_SQL, DiagnosticErrorType.POLICY_VIOLATION
    return ErrorCode.INVALID_ARGUMENT, DiagnosticErrorType.MISSING_SQL


def _effective_timeout(request: CommandRequest, profile: ProfileRecord) -> float | None:
    """Prefer the request timeout, then a positive profile timeout, else the runner default."""

    if request.sql_timeout_seconds is not None:
        return request.sql_timeout_seconds
    if profile.settings.query_timeout > 0:
        return profile.settings.query_timeout
    return None


__all__ = ["ActualPlanService", "actual_plan_diagnostic_sql", "parse_read_only_actual_plan"]
