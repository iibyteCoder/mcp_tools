"""Click command boundary for the JSON-only MySQL CLI."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, TypeVar

import click

from mysql_cli import __version__
from mysql_cli.command_model import (
    CommandAction,
    CommandGroup,
    CommandRequest,
    DiagnosticErrorType,
    DiagnosticStatus,
    ErrorCode,
    ExitCode,
    InputSource,
    OutputMode,
    SqlInputSpec,
)
from mysql_cli.errors import CliFailure, ErrorDetail
from mysql_cli.input_loader import LoadedInputs, load_inputs
from mysql_cli.inspection_service import InspectionService
from mysql_cli.json_codec import encode_json_document
from mysql_cli.output_model import (
    CommandDiagnosticData,
    DiagnosticMetadata,
    ErrorBody,
    ErrorEnvelope,
    InspectionCommandData,
    ParameterDiagnostic,
    ProfileCommandData,
    SqlCommandData,
    SqlDiagnostic,
    SuccessEnvelope,
)
from mysql_cli.profile_commands import execute_profile_command
from mysql_cli.profile_models import ProfileName, ProfileSettingsPatch
from mysql_cli.profile_service import ProfileService, ProfileServiceError, ProfileServiceErrorCode
from mysql_cli.profile_store import JsonProfileStore, ProfileStoreError
from mysql_cli.secret_store import KeyringSecretStore
from mysql_cli.sql_service import SqlExecutionService
from mysql_client import (
    ClientError,
    DatabaseName,
    ExecutionPolicy,
    ExecutionPolicyError,
    MySqlSqlParser,
    ParsedSql,
    SqlParseError,
    TableName,
    TransactionAction,
    UnsupportedSqlError,
    error_report_from_exception,
    validate_execution_policy,
)
from mysql_client import ErrorCode as ClientErrorCode

if TYPE_CHECKING:
    from collections.abc import Sequence


CommandCallback = TypeVar("CommandCallback", bound=Callable[..., object])


class InspectionExecutor(Protocol):
    """Typed inspection service dependency used by the command boundary."""

    async def execute(self, request: CommandRequest) -> InspectionCommandData: ...


class SqlExecutor(Protocol):
    """Typed SQL service dependency used by the command boundary."""

    async def execute(self, request: CommandRequest, inputs: LoadedInputs) -> SqlCommandData: ...


@dataclass(slots=True)
class CliRuntime:
    """Mutable invocation state kept outside Click command callbacks."""

    profile_service: ProfileService
    inspection_service: InspectionExecutor | None = None
    sql_service: SqlExecutor | None = None
    selected_profile: ProfileName | None = None
    request: CommandRequest | None = None

    @classmethod
    def create_default(cls) -> CliRuntime:
        """Build production services without contacting a database."""

        profiles = ProfileService(
            JsonProfileStore(lock_timeout=JsonProfileStore.CLI_LOCK_TIMEOUT_SECONDS),
            KeyringSecretStore(),
        )
        return cls(profile_service=profiles)


class _TypedParamType(click.ParamType[object, object]):
    """Convert a Click string directly into a strict domain value."""

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__()


class _ProfileNameType(_TypedParamType):
    def __init__(self) -> None:
        super().__init__("profile-name")

    def convert(
        self,
        value: object,
        param: click.Parameter | None,
        ctx: click.Context | None,
    ) -> ProfileName:
        if isinstance(value, ProfileName):
            return value
        if not isinstance(value, str):
            self.fail("profile name must be text", param, ctx)
        try:
            return ProfileName(value=value)
        except ValueError as exc:
            self.fail("profile name is invalid", param, ctx)
            raise AssertionError("Click ParamType.fail did not raise") from exc


class _DatabaseNameType(_TypedParamType):
    def __init__(self) -> None:
        super().__init__("database-name")

    def convert(
        self,
        value: object,
        param: click.Parameter | None,
        ctx: click.Context | None,
    ) -> DatabaseName:
        if isinstance(value, DatabaseName):
            return value
        if not isinstance(value, str):
            self.fail("database name must be text", param, ctx)
        try:
            return DatabaseName(value=value)
        except ValueError as exc:
            self.fail("database name is invalid", param, ctx)
            raise AssertionError("Click ParamType.fail did not raise") from exc


class _TableNameType(_TypedParamType):
    def __init__(self) -> None:
        super().__init__("table-name")

    def convert(
        self,
        value: object,
        param: click.Parameter | None,
        ctx: click.Context | None,
    ) -> TableName:
        if isinstance(value, TableName):
            return value
        if not isinstance(value, str):
            self.fail("table name must be text", param, ctx)
        try:
            return TableName(value=value)
        except ValueError as exc:
            self.fail("table name is invalid", param, ctx)
            raise AssertionError("Click ParamType.fail did not raise") from exc


PROFILE_NAME = _ProfileNameType()
DATABASE_NAME = _DatabaseNameType()
TABLE_NAME = _TableNameType()
PATH = click.Path(path_type=Path)
SQL_PATH = click.Path(path_type=Path, allow_dash=True)
POSITIVE_INTEGER = click.IntRange(min=1)
NON_NEGATIVE_INTEGER = click.IntRange(min=0)
POSITIVE_FLOAT = click.FloatRange(min=0.0, min_open=True)
TRANSACTION = click.Choice(tuple(action.value for action in TransactionAction), case_sensitive=True)


class JsonClickGroup(click.Group):
    """Run Click in non-standalone mode and render all failures as JSON."""

    def main(  # type: ignore[override]
        self,
        args: Sequence[str] | None = None,
        prog_name: str | None = None,
        complete_var: str | None = None,
        standalone_mode: bool = True,
        **extra: object,
    ) -> int | None:
        provided_runtime = extra.get("obj")
        runtime = provided_runtime if isinstance(provided_runtime, CliRuntime) else CliRuntime.create_default()
        extra["obj"] = runtime
        try:
            raw_result = super().main(
                args=args,
                prog_name=prog_name,
                complete_var=complete_var,
                standalone_mode=False,
                **extra,
            )
            result = None if raw_result is None else int(raw_result)
        except click.exceptions.Exit as control:
            result = int(control.exit_code)
        except CliFailure as failure:
            result = _render_failure(failure, runtime)
        except ProfileStoreError as error:
            result = _render_failure(_profile_store_failure(error), runtime)
        except ProfileServiceError as error:
            result = _render_failure(_profile_service_failure(error), runtime)
        except ClientError as error:
            result = _render_failure(_client_failure(error), runtime)
        except click.Abort:
            result = _render_failure(_cancelled_failure(), runtime)
        except click.ClickException as error:
            result = _render_failure(_click_failure(error), runtime)
        except KeyboardInterrupt:
            result = _render_failure(_cancelled_failure(), runtime)
        except Exception:
            result = _render_failure(_internal_failure(), runtime)
        if standalone_mode and result not in (None, 0):
            raise SystemExit(int(result))
        return result


@click.group(
    cls=JsonClickGroup,
    context_settings={"help_option_names": ["-h", "--help"], "max_content_width": 120},
)
@click.version_option(version=__version__, prog_name="db-mysql", message="%(prog)s %(version)s")
@click.option("--json", "json_output", is_flag=True, help="emit one JSON document")
@click.option("--profile", "selected_profile", type=PROFILE_NAME, help="select a profile for this invocation")
@click.pass_context
def cli(ctx: click.Context, json_output: bool, selected_profile: ProfileName | None) -> None:
    """JSON-only MySQL command line foundation."""

    del json_output
    runtime = _runtime(ctx)
    runtime.selected_profile = selected_profile


@cli.command("help")
@click.pass_context
def help_command(ctx: click.Context) -> None:
    """Show the complete command tree."""

    click.echo(ctx.find_root().get_help())


@cli.group()
def profile() -> None:
    """Manage named connection profiles and directory bindings."""


@profile.command("list")
@click.pass_context
def profile_list(ctx: click.Context) -> None:
    """List configured profiles."""

    _execute(ctx, CommandRequest(group=CommandGroup.PROFILE, action=CommandAction.LIST))


@profile.command("show")
@click.argument("name", type=PROFILE_NAME)
@click.pass_context
def profile_show(ctx: click.Context, name: ProfileName) -> None:
    """Show one profile without its password."""

    _execute(ctx, CommandRequest(group=CommandGroup.PROFILE, action=CommandAction.SHOW, profile_name=name))


@profile.command("set")
@click.argument("name", type=PROFILE_NAME)
@click.option("--host", type=str)
@click.option("--port", type=click.IntRange(min=1, max=65_535))
@click.option("--user", type=str)
@click.option("--database", type=str)
@click.option("--no-database", is_flag=True)
@click.option("--charset", type=str)
@click.option("--connect-timeout", type=POSITIVE_FLOAT)
@click.option("--read-timeout", type=POSITIVE_FLOAT)
@click.option("--password", type=str)
@click.option("--no-password", is_flag=True)
@click.option("--no-bind", is_flag=True)
@click.pass_context
def profile_set(
    ctx: click.Context,
    name: ProfileName,
    host: str | None,
    port: int | None,
    user: str | None,
    database: str | None,
    no_database: bool,
    charset: str | None,
    connect_timeout: float | None,
    read_timeout: float | None,
    password: str | None,
    no_password: bool,
    no_bind: bool,
) -> None:
    """Create or update one profile."""

    if no_database and database is not None:
        raise _argument_failure("--database and --no-database cannot be used together", "--database/--no-database")
    if no_password and password is not None:
        raise _argument_failure("--password and --no-password cannot be used together", "--password/--no-password")
    _execute(
        ctx,
        CommandRequest(
            group=CommandGroup.PROFILE,
            action=CommandAction.SET,
            profile_name=name,
            profile_settings=ProfileSettingsPatch(
                host=host,
                port=port,
                user=user,
                database=None if no_database else database,
                charset=charset,
                connect_timeout=connect_timeout,
                read_timeout=read_timeout,
                clear_database=no_database,
            ),
            profile_password=password,
            profile_clear_password=no_password,
            profile_no_bind=no_bind,
        ),
    )


@profile.command("validate")
@click.argument("name", type=PROFILE_NAME)
@click.pass_context
def profile_validate(ctx: click.Context, name: ProfileName) -> None:
    """Validate one profile by opening a real connection."""

    _execute(ctx, CommandRequest(group=CommandGroup.PROFILE, action=CommandAction.VALIDATE, profile_name=name))


@profile.command("bind")
@click.argument("name", type=PROFILE_NAME)
@click.option("--path", type=PATH)
@click.pass_context
def profile_bind(ctx: click.Context, name: ProfileName, path: Path | None) -> None:
    """Bind a profile to a directory."""

    _execute(ctx, CommandRequest(group=CommandGroup.PROFILE, action=CommandAction.BIND, profile_name=name, profile_path=path))


@profile.command("unbind")
@click.option("--path", type=PATH)
@click.pass_context
def profile_unbind(ctx: click.Context, path: Path | None) -> None:
    """Remove the exact directory binding."""

    _execute(ctx, CommandRequest(group=CommandGroup.PROFILE, action=CommandAction.UNBIND, profile_path=path))


@profile.command("rename")
@click.argument("old", type=PROFILE_NAME)
@click.argument("new", type=PROFILE_NAME)
@click.pass_context
def profile_rename(ctx: click.Context, old: ProfileName, new: ProfileName) -> None:
    """Rename a profile without overwriting another profile."""

    _execute(
        ctx,
        CommandRequest(
            group=CommandGroup.PROFILE,
            action=CommandAction.RENAME,
            profile_name=old,
            profile_new_name=new,
        ),
    )


@profile.command("remove")
@click.argument("name", type=PROFILE_NAME)
@click.pass_context
def profile_remove(ctx: click.Context, name: ProfileName) -> None:
    """Remove a profile and its bindings."""

    _execute(ctx, CommandRequest(group=CommandGroup.PROFILE, action=CommandAction.REMOVE, profile_name=name))


@cli.group()
def server() -> None:
    """Inspect the selected server."""


@server.command("inspect")
@click.pass_context
def server_inspect(ctx: click.Context) -> None:
    """Inspect server identity and connection details."""

    _execute(ctx, CommandRequest(group=CommandGroup.SERVER, action=CommandAction.INSPECT))


@server.command("capabilities")
@click.pass_context
def server_capabilities(ctx: click.Context) -> None:
    """Inspect server capabilities."""

    _execute(ctx, CommandRequest(group=CommandGroup.SERVER, action=CommandAction.CAPABILITIES))


@cli.group()
def schema() -> None:
    """Inspect databases, tables, indexes and statistics."""


@schema.command("databases")
@click.pass_context
def schema_databases(ctx: click.Context) -> None:
    """List databases."""

    _execute(ctx, CommandRequest(group=CommandGroup.SCHEMA, action=CommandAction.DATABASES))


@schema.command("tables")
@click.option("--database", type=DATABASE_NAME)
@click.pass_context
def schema_tables(ctx: click.Context, database: DatabaseName | None) -> None:
    """List tables in a database."""

    _execute(ctx, CommandRequest(group=CommandGroup.SCHEMA, action=CommandAction.TABLES, schema_database=database))


@schema.command("describe")
@click.option("--database", type=DATABASE_NAME)
@click.option("--table", type=TABLE_NAME, required=True)
@click.pass_context
def schema_describe(ctx: click.Context, database: DatabaseName | None, table: TableName) -> None:
    """Describe one table."""

    _execute(
        ctx,
        CommandRequest(
            group=CommandGroup.SCHEMA,
            action=CommandAction.DESCRIBE,
            schema_database=database,
            schema_table=table,
        ),
    )


@schema.command("indexes")
@click.option("--database", type=DATABASE_NAME)
@click.option("--table", type=TABLE_NAME, required=True)
@click.pass_context
def schema_indexes(ctx: click.Context, database: DatabaseName | None, table: TableName) -> None:
    """List indexes for one table."""

    _execute(
        ctx,
        CommandRequest(
            group=CommandGroup.SCHEMA,
            action=CommandAction.INDEXES,
            schema_database=database,
            schema_table=table,
        ),
    )


@schema.command("stats")
@click.option("--database", type=DATABASE_NAME)
@click.option("--table", type=TABLE_NAME)
@click.pass_context
def schema_stats(ctx: click.Context, database: DatabaseName | None, table: TableName | None) -> None:
    """Inspect schema or table statistics."""

    _execute(
        ctx,
        CommandRequest(
            group=CommandGroup.SCHEMA,
            action=CommandAction.STATS,
            schema_database=database,
            schema_table=table,
        ),
    )


@cli.group()
def sql() -> None:
    """Parse or execute one SQL statement."""


def _sql_input_options(command: CommandCallback) -> CommandCallback:
    """Add common mutually exclusive SQL input options to one command."""

    command_with_text = click.option("--sql", "sql_text", type=str, help="inline SQL text")(command)
    command_with_file = click.option(
        "--sql-file", "sql_file", type=SQL_PATH, help="SQL file path; - reads stdin"
    )(command_with_text)
    return command_with_file


@sql.command("read")
@_sql_input_options
@click.option("--params-file", type=PATH)
@click.option("--max-rows", type=POSITIVE_INTEGER)
@click.option("--max-bytes", type=POSITIVE_INTEGER)
@click.option("--timeout", "timeout_seconds", type=POSITIVE_FLOAT)
@click.pass_context
def sql_read(
    ctx: click.Context,
    sql_text: str | None,
    sql_file: Path | None,
    params_file: Path | None,
    max_rows: int | None,
    max_bytes: int | None,
    timeout_seconds: float | None,
) -> None:
    """Read rows from one SQL statement."""

    _execute(
        ctx,
        _sql_request(
            CommandAction.READ,
            selected_profile=_selected_profile(ctx),
            sql_text=sql_text,
            sql_file=sql_file,
            params_file=params_file,
            max_rows=max_rows,
            max_bytes=max_bytes,
            timeout_seconds=timeout_seconds,
        ),
    )


@sql.command("write")
@_sql_input_options
@click.option("--params-file", type=PATH)
@click.option("--transaction", type=TRANSACTION, default=TransactionAction.COMMIT.value, show_default=True)
@click.option("--timeout", "timeout_seconds", type=POSITIVE_FLOAT)
@click.pass_context
def sql_write(
    ctx: click.Context,
    sql_text: str | None,
    sql_file: Path | None,
    params_file: Path | None,
    transaction: str,
    timeout_seconds: float | None,
) -> None:
    """Execute one authorized mutation or DDL statement."""

    _execute(
        ctx,
        _sql_request(
            CommandAction.WRITE,
            selected_profile=_selected_profile(ctx),
            sql_text=sql_text,
            sql_file=sql_file,
            params_file=params_file,
            transaction=TransactionAction(transaction),
            timeout_seconds=timeout_seconds,
        ),
    )


@sql.command("explain")
@_sql_input_options
@click.option("--params-file", type=PATH)
@click.option("--timeout", "timeout_seconds", type=POSITIVE_FLOAT)
@click.pass_context
def sql_explain(
    ctx: click.Context,
    sql_text: str | None,
    sql_file: Path | None,
    params_file: Path | None,
    timeout_seconds: float | None,
) -> None:
    """Execute one EXPLAIN statement exactly as supplied."""

    _execute(
        ctx,
        _sql_request(
            CommandAction.EXPLAIN,
            selected_profile=_selected_profile(ctx),
            sql_text=sql_text,
            sql_file=sql_file,
            params_file=params_file,
            timeout_seconds=timeout_seconds,
        ),
    )


@sql.command("benchmark")
@_sql_input_options
@click.option("--params-file", type=PATH)
@click.option("--iterations", type=POSITIVE_INTEGER)
@click.option("--warmup-iterations", type=NON_NEGATIVE_INTEGER)
@click.option("--timeout", "timeout_seconds", type=POSITIVE_FLOAT)
@click.pass_context
def sql_benchmark(
    ctx: click.Context,
    sql_text: str | None,
    sql_file: Path | None,
    params_file: Path | None,
    iterations: int | None,
    warmup_iterations: int | None,
    timeout_seconds: float | None,
) -> None:
    """Measure one SQL statement."""

    _execute(
        ctx,
        _sql_request(
            CommandAction.BENCHMARK,
            selected_profile=_selected_profile(ctx),
            sql_text=sql_text,
            sql_file=sql_file,
            params_file=params_file,
            iterations=iterations,
            warmup_iterations=warmup_iterations,
            timeout_seconds=timeout_seconds,
        ),
    )


@sql.command("compare")
@click.option("--left-sql", type=str)
@click.option("--left-sql-file", type=SQL_PATH)
@click.option("--right-sql", type=str)
@click.option("--right-sql-file", type=SQL_PATH)
@click.option("--left-params-file", type=PATH)
@click.option("--right-params-file", type=PATH)
@click.option("--key-column", "key_columns", multiple=True)
@click.option("--max-diff-samples", type=NON_NEGATIVE_INTEGER)
@click.option("--timeout", "timeout_seconds", type=POSITIVE_FLOAT)
@click.pass_context
def sql_compare(
    ctx: click.Context,
    left_sql: str | None,
    left_sql_file: Path | None,
    right_sql: str | None,
    right_sql_file: Path | None,
    left_params_file: Path | None,
    right_params_file: Path | None,
    key_columns: tuple[str, ...],
    max_diff_samples: int | None,
    timeout_seconds: float | None,
) -> None:
    """Compare the results of two SQL statements."""

    _execute(
        ctx,
        CommandRequest(
            group=CommandGroup.SQL,
            action=CommandAction.COMPARE,
            selected_profile=_selected_profile(ctx),
            compare_left_sql_input=_sql_spec(left_sql, left_sql_file, label="left SQL", allow_stdin=False),
            compare_right_sql_input=_sql_spec(right_sql, right_sql_file, label="right SQL", allow_stdin=False),
            compare_left_params_file=left_params_file,
            compare_right_params_file=right_params_file,
            compare_key_columns=key_columns,
            compare_max_diff_samples=max_diff_samples,
            sql_timeout_seconds=timeout_seconds,
        ),
    )


def _runtime(ctx: click.Context) -> CliRuntime:
    value = ctx.ensure_object(CliRuntime)
    if not isinstance(value, CliRuntime):
        raise TypeError("Click context object must be CliRuntime")
    return value


def _selected_profile(ctx: click.Context) -> ProfileName | None:
    return _runtime(ctx).selected_profile


def _execute(ctx: click.Context, request: CommandRequest) -> None:
    runtime = _runtime(ctx)
    if request.selected_profile is None and runtime.selected_profile is not None:
        request = replace(request, selected_profile=runtime.selected_profile)
    runtime.request = request
    if request.group is CommandGroup.PROFILE:
        profile_data: ProfileCommandData = asyncio.run(execute_profile_command(request, runtime.profile_service))
        _write_success(profile_data, request)
        return
    if request.group in {CommandGroup.SERVER, CommandGroup.SCHEMA}:
        inspection_service = runtime.inspection_service or InspectionService(runtime.profile_service)
        runtime.inspection_service = inspection_service
        inspection_data: InspectionCommandData = asyncio.run(inspection_service.execute(request))
        _write_success(inspection_data, request)
        return
    if request.group is not CommandGroup.SQL:
        raise ValueError("unsupported command group")
    stdin_text = _read_stdin_if_needed(ctx, request)
    loaded = load_inputs(request, stdin_text=stdin_text)
    if request.selected_profile is not None:
        sql_service = runtime.sql_service or SqlExecutionService(runtime.profile_service)
        runtime.sql_service = sql_service
        sql_data: SqlCommandData = asyncio.run(sql_service.execute(request, loaded))
        _write_success(sql_data, request)
        return
    _write_success(_diagnose(request, loaded), request)


def _sql_request(
    action: CommandAction,
    *,
    selected_profile: ProfileName | None,
    sql_text: str | None,
    sql_file: Path | None,
    params_file: Path | None,
    max_rows: int | None = None,
    max_bytes: int | None = None,
    iterations: int | None = None,
    warmup_iterations: int | None = None,
    transaction: TransactionAction = TransactionAction.COMMIT,
    timeout_seconds: float | None = None,
) -> CommandRequest:
    return CommandRequest(
        group=CommandGroup.SQL,
        action=action,
        selected_profile=selected_profile,
        sql_input=_sql_spec(sql_text, sql_file, label="SQL", allow_stdin=True),
        params_file=params_file,
        sql_max_rows=max_rows,
        sql_max_bytes=max_bytes,
        sql_iterations=iterations,
        sql_warmup_iterations=warmup_iterations,
        sql_transaction=transaction,
        sql_timeout_seconds=timeout_seconds,
    )


def _sql_spec(sql_text: str | None, sql_file: Path | None, *, label: str, allow_stdin: bool) -> SqlInputSpec:
    if sql_text is not None and sql_file is not None:
        raise _argument_failure(
            f"{label} cannot use text and file together",
            "--sql/--sql-file" if label == "SQL" else f"{label}/file",
            error_type=DiagnosticErrorType.MUTUALLY_EXCLUSIVE_INPUTS,
        )
    if sql_text is not None:
        return SqlInputSpec.inline(sql_text)
    if sql_file is None:
        raise _argument_failure(
            f"{label} is required",
            "--sql|--sql-file" if label == "SQL" else label,
            error_type=DiagnosticErrorType.MISSING_SQL,
        )
    if sql_file == Path("-"):
        if not allow_stdin:
            raise _argument_failure(f"{label} does not support standard input", label)
        return SqlInputSpec.stdin()
    return SqlInputSpec.file(sql_file)


def _read_stdin_if_needed(ctx: click.Context, request: CommandRequest) -> str | None:
    needed = (
        (request.sql_input is not None and request.sql_input.source is InputSource.STDIN)
        or (request.compare_left_sql_input is not None and request.compare_left_sql_input.source is InputSource.STDIN)
        or (request.compare_right_sql_input is not None and request.compare_right_sql_input.source is InputSource.STDIN)
    )
    return sys.stdin.read() if needed else None


def _diagnose(request: CommandRequest, loaded: LoadedInputs) -> CommandDiagnosticData:
    sql_diagnostic: SqlDiagnostic | None = None
    if loaded.sql is not None:
        try:
            parsed = MySqlSqlParser().parse(loaded.sql)
        except SqlParseError as exc:
            raise _sql_failure(
                code=ErrorCode.INVALID_SQL,
                message=exc.message,
                error_type=DiagnosticErrorType.SQL_PARSE,
                request=request,
            ) from exc
        except UnsupportedSqlError as exc:
            raise _sql_failure(
                code=ErrorCode.UNSUPPORTED_SQL,
                message=exc.message,
                error_type=DiagnosticErrorType.POLICY_VIOLATION,
                request=request,
            ) from exc
        _validate_policy_if_required(request.action, parsed, request=request)
        sql_diagnostic = SqlDiagnostic(
            source=request.sql_input.source if request.sql_input is not None else InputSource.INLINE,
            statement_type=parsed.statement_type,
            read_only=parsed.is_read_only,
            write=parsed.is_write,
            requires_explicit_transaction=parsed.requires_explicit_transaction,
            explain_analyze=parsed.is_explain_analyze,
            text_length=len(parsed.normalized_sql),
        )
    parameter_diagnostic = None
    if loaded.parameters is not None:
        parameter_diagnostic = ParameterDiagnostic(
            source=InputSource.PARAMS_FILE,
            kind=loaded.parameters.kind,
            count=loaded.parameters.count,
            path=loaded.parameters.source,
        )
    return CommandDiagnosticData(
        status=DiagnosticStatus.PARSED,
        command_group=request.group,
        action=request.action,
        sql=sql_diagnostic,
        parameters=parameter_diagnostic,
    )


def _validate_policy_if_required(action: CommandAction, parsed: ParsedSql, *, request: CommandRequest) -> None:
    if action is CommandAction.READ:
        policy = ExecutionPolicy.READ_ONLY
    elif action is CommandAction.WRITE:
        policy = ExecutionPolicy.WRITE
    elif action is CommandAction.EXPLAIN:
        policy = ExecutionPolicy.EXPLAIN
    else:
        return
    try:
        validate_execution_policy(parsed, policy)
    except ExecutionPolicyError as exc:
        raise _sql_failure(
            code=ErrorCode.UNSUPPORTED_SQL,
            message=exc.message,
            error_type=DiagnosticErrorType.POLICY_VIOLATION,
            request=request,
        ) from exc


def _sql_failure(
    *,
    code: ErrorCode,
    message: str,
    error_type: DiagnosticErrorType,
    request: CommandRequest | None,
) -> CliFailure:
    source = request.sql_input.source if request is not None and request.sql_input is not None else None
    return CliFailure(
        code=code,
        message=message,
        retryable=False,
        details=(ErrorDetail(error_type=error_type, argument="--sql|--sql-file", source=source),),
        exit_code=ExitCode.INVALID_ARGUMENT,
    )


def _write_success(
    data: CommandDiagnosticData | ProfileCommandData | InspectionCommandData | SqlCommandData,
    request: CommandRequest,
) -> None:
    envelope = SuccessEnvelope(
        ok=True,
        data=data,
        meta=DiagnosticMetadata(
            command_group=request.group,
            action=request.action,
            input_source=request.sql_input.source if request.sql_input is not None else None,
        ),
    )
    click.echo(encode_json_document(envelope), nl=False)


def _write_failure(failure: CliFailure, request: CommandRequest | None) -> None:
    envelope = ErrorEnvelope(
        ok=False,
        error=ErrorBody(
            code=failure.code,
            message=failure.message,
            retryable=failure.retryable,
            details=failure.details,
            write_outcome=failure.write_outcome,
            differences=failure.differences,
        ),
        meta=DiagnosticMetadata(
            command_group=request.group if request is not None else None,
            action=request.action if request is not None else None,
            input_source=request.sql_input.source if request is not None and request.sql_input is not None else None,
            output_mode=OutputMode.JSON,
        ),
    )
    click.echo(encode_json_document(envelope), nl=False)


def _render_failure(failure: CliFailure, runtime: CliRuntime) -> int:
    _write_failure(failure, runtime.request)
    return int(failure.exit_code)


def _argument_failure(
    message: str,
    argument: str,
    *,
    error_type: DiagnosticErrorType = DiagnosticErrorType.ARGUMENT_SYNTAX,
) -> CliFailure:
    return CliFailure(
        code=ErrorCode.INVALID_ARGUMENT,
        message=message,
        retryable=False,
        details=(ErrorDetail(error_type=error_type, argument=argument),),
        exit_code=ExitCode.INVALID_ARGUMENT,
    )


def _click_failure(error: click.ClickException) -> CliFailure:
    if isinstance(error, click.exceptions.NoSuchCommand):
        return CliFailure(
            code=ErrorCode.UNKNOWN_COMMAND,
            message="unknown command",
            retryable=False,
            details=(ErrorDetail(error_type=DiagnosticErrorType.UNKNOWN_COMMAND, argument=error.message),),
            exit_code=ExitCode.INVALID_ARGUMENT,
        )
    argument: object = None
    if isinstance(error, click.exceptions.BadParameter):
        argument = error.param_hint
    elif isinstance(error, click.exceptions.NoSuchOption):
        argument = error.option_name
    elif isinstance(error, click.exceptions.MissingParameter):
        argument = error.param_hint
    message = error.message or str(error) or "command argument is invalid"
    argument_name = _argument_name(argument) or "command"
    return _argument_failure(message, argument_name, error_type=DiagnosticErrorType.ARGUMENT_SYNTAX)


def _argument_name(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, tuple) and all(isinstance(item, str) for item in value):
        return "/".join(value)
    return None


def _cancelled_failure() -> CliFailure:
    return CliFailure(
        code=ErrorCode.CANCELLED,
        message="operation cancelled",
        retryable=False,
        details=(ErrorDetail(error_type=DiagnosticErrorType.CANCELLED),),
        exit_code=ExitCode.EXECUTION_ERROR,
    )


def _internal_failure() -> CliFailure:
    return CliFailure(
        code=ErrorCode.INTERNAL_ERROR,
        message="internal error",
        retryable=False,
        details=(ErrorDetail(error_type=DiagnosticErrorType.EXECUTION),),
        exit_code=ExitCode.INTERNAL_ERROR,
    )


def _profile_store_failure(error: ProfileStoreError) -> CliFailure:
    mapping = {
        "profile_registry_corrupt": (ErrorCode.PROFILE_REGISTRY_CORRUPT, DiagnosticErrorType.PROFILE_REGISTRY_CORRUPT),
        "profile_registry_version_unsupported": (
            ErrorCode.PROFILE_REGISTRY_VERSION,
            DiagnosticErrorType.PROFILE_REGISTRY_VERSION,
        ),
        "profile_registry_locked": (ErrorCode.PROFILE_REGISTRY_LOCKED, DiagnosticErrorType.PROFILE_REGISTRY_LOCKED),
    }
    code, error_type = mapping.get(
        error.code.value,
        (ErrorCode.INPUT_ERROR, DiagnosticErrorType.FILE_READ_ERROR),
    )
    exit_code = ExitCode.PROFILE_ERROR if code is not ErrorCode.INPUT_ERROR else ExitCode.INPUT_ERROR
    return CliFailure(
        code=code,
        message=error.message,
        retryable=False,
        details=(ErrorDetail(error_type=error_type),),
        exit_code=exit_code,
    )


def _profile_service_failure(error: ProfileServiceError) -> CliFailure:
    mapping = {
        ProfileServiceErrorCode.NOT_FOUND: (ErrorCode.PROFILE_NOT_FOUND, DiagnosticErrorType.PROFILE_NOT_FOUND),
        ProfileServiceErrorCode.CONFLICT: (ErrorCode.PROFILE_CONFLICT, DiagnosticErrorType.PROFILE_CONFLICT),
        ProfileServiceErrorCode.INVALID: (ErrorCode.PROFILE_INVALID, DiagnosticErrorType.ARGUMENT_SYNTAX),
        ProfileServiceErrorCode.SECRET_MISSING: (ErrorCode.SECRET_STORE, DiagnosticErrorType.SECRET_STORE),
        ProfileServiceErrorCode.SECRET_STORE: (ErrorCode.SECRET_STORE, DiagnosticErrorType.SECRET_STORE),
        ProfileServiceErrorCode.VALIDATION_FAILED: (
            ErrorCode.PROFILE_VALIDATION_FAILED,
            DiagnosticErrorType.PROFILE_VALIDATION,
        ),
    }
    code, error_type = mapping[error.code]
    return CliFailure(
        code=code,
        message=error.message,
        retryable=False,
        details=(ErrorDetail(error_type=error_type),),
        exit_code=ExitCode.PROFILE_ERROR,
    )


def _client_failure(error: ClientError) -> CliFailure:
    report = error_report_from_exception(error)
    mapping = {
        ClientErrorCode.INVALID_ARGUMENT: (ErrorCode.INVALID_ARGUMENT, DiagnosticErrorType.ARGUMENT_SYNTAX),
        ClientErrorCode.CONFIGURATION_FAILED: (ErrorCode.CONFIGURATION_FAILED, DiagnosticErrorType.CONFIGURATION),
        ClientErrorCode.CONNECTION_FAILED: (ErrorCode.CONNECTION_FAILED, DiagnosticErrorType.CONNECTION),
        ClientErrorCode.AUTHENTICATION_FAILED: (ErrorCode.AUTHENTICATION_FAILED, DiagnosticErrorType.AUTHENTICATION),
        ClientErrorCode.DATABASE_NOT_FOUND: (ErrorCode.DATABASE_NOT_FOUND, DiagnosticErrorType.DATABASE_NOT_FOUND),
        ClientErrorCode.TIMEOUT: (ErrorCode.TIMEOUT, DiagnosticErrorType.TIMEOUT),
        ClientErrorCode.CANCELLED: (ErrorCode.CANCELLED, DiagnosticErrorType.CANCELLED),
        ClientErrorCode.QUERY_FAILED: (ErrorCode.EXECUTION_FAILED, DiagnosticErrorType.EXECUTION),
        ClientErrorCode.COMPARISON_FAILED: (ErrorCode.COMPARISON_FAILED, DiagnosticErrorType.COMPARISON),
        ClientErrorCode.UNSUPPORTED_SQL: (ErrorCode.UNSUPPORTED_SQL, DiagnosticErrorType.POLICY_VIOLATION),
        ClientErrorCode.INVALID_SQL: (ErrorCode.INVALID_SQL, DiagnosticErrorType.SQL_PARSE),
        ClientErrorCode.INTERNAL_ERROR: (ErrorCode.INTERNAL_ERROR, DiagnosticErrorType.EXECUTION),
    }
    code, error_type = mapping[error.code]
    exit_code = ExitCode.INVALID_ARGUMENT if code is ErrorCode.INVALID_ARGUMENT else ExitCode.EXECUTION_ERROR
    return CliFailure(
        code=code,
        message=error.message,
        retryable=False,
        details=(ErrorDetail(error_type=error_type),),
        exit_code=exit_code,
        write_outcome=report.write_outcome,
        differences=report.differences,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return a stable process exit code."""

    arguments = tuple(sys.argv[1:] if argv is None else argv)
    result = cli.main(args=arguments, prog_name="db-mysql", standalone_mode=False)
    return 0 if result is None else int(result)


__all__ = ["CliRuntime", "cli", "main"]
