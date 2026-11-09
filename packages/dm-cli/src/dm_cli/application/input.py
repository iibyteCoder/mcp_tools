"""Typed loading and validation of SQL and positional parameter inputs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from db_cli_kit.json_codec import JsonDocumentError, is_json_array, parse_json_document
from dm_cli.application.errors import CliFailure, ErrorDetail
from dm_cli.domain.command import (
    CommandRequest,
    DiagnosticErrorType,
    ErrorCode,
    ExitCode,
    InputSource,
    ParameterKind,
    SqlInputSpec,
)
from dm_client.domain.requests import SqlInput
from dm_client.domain.values import SqlText

if TYPE_CHECKING:
    from pathlib import Path

    from db_cli_kit.json_codec import JsonArray
    from dm_client.domain.values import DatabaseValue

PARAMS_FILE_ARGUMENT: Final[str] = "--params-file"
SQL_INPUT_ARGUMENT: Final[str] = "--sql/--sql-file"
COMPARE_LEFT_SQL_ARGUMENT: Final[str] = "--left-sql/--left-sql-file"
COMPARE_RIGHT_SQL_ARGUMENT: Final[str] = "--right-sql/--right-sql-file"
COMPARE_SQL_ARGUMENT: Final[str] = "--left-sql/--left-sql-file and --right-sql/--right-sql-file"
STDIN_INPUT_NAME: Final[str] = "stdin"
PARAMS_ARRAY_MESSAGE: Final[str] = (
    "DM accepts positional ? parameters only and requires a top-level JSON array"
)
EMPTY_SQL_MESSAGE: Final[str] = "SQL input must not be empty"


@dataclass(frozen=True, slots=True, kw_only=True)
class ParameterDocument:
    """A top-level JSON array loaded from ``--params-file``."""

    kind: ParameterKind
    bindings: tuple[DatabaseValue, ...]
    source: Path

    @property
    def count(self) -> int:
        """Return the number of positional parameters without exposing values."""

        return len(self.bindings)


@dataclass(frozen=True, slots=True, kw_only=True)
class LoadedInputs:
    """Resolved inputs passed into the command diagnostic stage."""

    sql: SqlInput | None
    parameters: ParameterDocument | None
    compare_left_sql: SqlInput | None = None
    compare_right_sql: SqlInput | None = None
    compare_left_parameters: ParameterDocument | None = None
    compare_right_parameters: ParameterDocument | None = None


def load_inputs(request: CommandRequest, *, stdin_text: str | None) -> LoadedInputs:
    """Load request inputs while preserving source provenance."""

    return LoadedInputs(
        sql=_load_sql(request.sql_input, stdin_text=stdin_text, argument=SQL_INPUT_ARGUMENT),
        parameters=_load_parameters(request.params_file),
        compare_left_sql=_load_sql(
            request.compare_left_sql_input,
            stdin_text=stdin_text,
            argument=COMPARE_LEFT_SQL_ARGUMENT,
        ),
        compare_right_sql=_load_sql(
            request.compare_right_sql_input,
            stdin_text=stdin_text,
            argument=COMPARE_RIGHT_SQL_ARGUMENT,
        ),
        compare_left_parameters=_load_parameters(request.compare_left_params_file),
        compare_right_parameters=_load_parameters(request.compare_right_params_file),
    )


def _load_sql(
    spec: SqlInputSpec | None,
    *,
    stdin_text: str | None,
    argument: str,
) -> SqlInput | None:
    if spec is None:
        return None
    if spec.source is InputSource.INLINE:
        if spec.text is None:
            raise _input_failure("inline SQL input is incomplete", DiagnosticErrorType.FILE_READ_ERROR)
        return _sql_input(spec.text, source=spec.source, name=None, argument=argument)
    if spec.source is InputSource.STDIN:
        if stdin_text is None:
            raise _input_failure(
                "standard input SQL was not provided",
                DiagnosticErrorType.FILE_READ_ERROR,
                source=spec.source,
            )
        return _sql_input(stdin_text, source=spec.source, name=STDIN_INPUT_NAME, argument=argument)
    if spec.source is InputSource.FILE and spec.path is not None:
        return _sql_input(
            _read_text(spec.path, source=spec.source),
            source=spec.source,
            name=str(spec.path),
            argument=argument,
        )
    raise _input_failure("SQL input source is invalid", DiagnosticErrorType.FILE_READ_ERROR, source=spec.source)


def _sql_input(text: str, *, source: InputSource, name: str | None, argument: str) -> SqlInput:
    """Reject empty SQL before the client value type raises a raw ``ValueError``."""

    if not text.strip():
        raise CliFailure(
            code=ErrorCode.INVALID_SQL,
            message=EMPTY_SQL_MESSAGE,
            retryable=False,
            details=(ErrorDetail(error_type=DiagnosticErrorType.SQL_PARSE, argument=argument, source=source),),
            exit_code=ExitCode.INVALID_ARGUMENT,
        )
    return SqlInput(text=SqlText(text), name=name)


def _load_parameters(path: Path | None) -> ParameterDocument | None:
    if path is None:
        return None
    text = _read_text(path, source=InputSource.PARAMS_FILE)
    try:
        document = parse_json_document(text)
    except JsonDocumentError as exc:
        raise _params_failure(
            "parameters file is not valid JSON",
            DiagnosticErrorType.INVALID_PARAMS_JSON,
            path=path,
        ) from exc
    if not is_json_array(document):
        raise _params_failure(PARAMS_ARRAY_MESSAGE, DiagnosticErrorType.INVALID_PARAMS_TYPE, path=path)
    return ParameterDocument(
        kind=ParameterKind.ARRAY,
        bindings=_parameter_values(document, path=path),
        source=path,
    )


def _parameter_values(values: JsonArray, *, path: Path) -> tuple[DatabaseValue, ...]:
    parameters: list[DatabaseValue] = []
    for value in values:
        if value is None or isinstance(value, (bool, int, float, str)):
            parameters.append(value)
            continue
        raise _params_failure(PARAMS_ARRAY_MESSAGE, DiagnosticErrorType.INVALID_PARAMS_TYPE, path=path)
    return tuple(parameters)


def _read_text(path: Path, *, source: InputSource) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise _read_failure("input file does not exist", DiagnosticErrorType.FILE_NOT_FOUND, path, source) from exc
    except UnicodeDecodeError as exc:
        raise _read_failure(
            "input file is not valid UTF-8",
            DiagnosticErrorType.FILE_DECODE_ERROR,
            path,
            source,
        ) from exc
    except OSError as exc:
        raise _read_failure("input file could not be read", DiagnosticErrorType.FILE_READ_ERROR, path, source) from exc


def _params_failure(message: str, error_type: DiagnosticErrorType, *, path: Path) -> CliFailure:
    return CliFailure(
        code=ErrorCode.INPUT_ERROR,
        message=message,
        retryable=False,
        details=(
            ErrorDetail(
                error_type=error_type,
                argument=PARAMS_FILE_ARGUMENT,
                source=InputSource.PARAMS_FILE,
                path=path,
            ),
        ),
        exit_code=ExitCode.INPUT_ERROR,
    )


def _read_failure(
    message: str,
    error_type: DiagnosticErrorType,
    path: Path,
    source: InputSource,
) -> CliFailure:
    return CliFailure(
        code=ErrorCode.INPUT_ERROR,
        message=message,
        retryable=False,
        details=(ErrorDetail(error_type=error_type, source=source, path=path),),
        exit_code=ExitCode.INPUT_ERROR,
    )


def _input_failure(
    message: str,
    error_type: DiagnosticErrorType,
    *,
    source: InputSource | None = None,
) -> CliFailure:
    return CliFailure(
        code=ErrorCode.INPUT_ERROR,
        message=message,
        retryable=False,
        details=(ErrorDetail(error_type=error_type, source=source),),
        exit_code=ExitCode.INPUT_ERROR,
    )


__all__ = [
    "COMPARE_LEFT_SQL_ARGUMENT",
    "COMPARE_RIGHT_SQL_ARGUMENT",
    "COMPARE_SQL_ARGUMENT",
    "EMPTY_SQL_MESSAGE",
    "PARAMS_ARRAY_MESSAGE",
    "PARAMS_FILE_ARGUMENT",
    "SQL_INPUT_ARGUMENT",
    "STDIN_INPUT_NAME",
    "LoadedInputs",
    "ParameterDocument",
    "load_inputs",
]
