"""Typed loading and validation of SQL and parameter input documents."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

from mysql_client import SqlInput
from mysql_command.command_model import (
    CommandRequest,
    DiagnosticErrorType,
    ErrorCode,
    ExitCode,
    InputSource,
    ParameterKind,
)
from mysql_command.errors import CliFailure, ErrorDetail
from mysql_command.json_codec import (
    JsonArray,
    JsonDocumentError,
    JsonObject,
    is_json_array,
    is_json_object,
    parse_json_document,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class ParameterDocument:
    """A top-level JSON object or array loaded from ``--params-file``."""

    kind: ParameterKind
    values: JsonObject | JsonArray
    source: Path

    @property
    def count(self) -> int:
        """Return the number of top-level parameters without exposing values."""

        return len(self.values)


@dataclass(frozen=True, slots=True, kw_only=True)
class LoadedInputs:
    """Resolved inputs passed into the command diagnostic stage."""

    sql: SqlInput | None
    parameters: ParameterDocument | None


def load_inputs(request: CommandRequest, *, stdin_text: str | None) -> LoadedInputs:
    """Load request inputs while preserving source provenance."""

    sql = _load_sql(request, stdin_text=stdin_text)
    parameters = _load_parameters(request.params_file)
    return LoadedInputs(sql=sql, parameters=parameters)


def _load_sql(request: CommandRequest, *, stdin_text: str | None) -> SqlInput | None:
    spec = request.sql_input
    if spec is None:
        return None
    if spec.source is InputSource.INLINE:
        if spec.text is None:
            raise _input_failure("内联 SQL 输入不完整", DiagnosticErrorType.FILE_READ_ERROR)
        return SqlInput.inline(spec.text)
    if spec.source is InputSource.STDIN:
        if stdin_text is None:
            raise _input_failure("未提供标准输入 SQL", DiagnosticErrorType.FILE_READ_ERROR, source=spec.source)
        return SqlInput.stdin(stdin_text)
    if spec.source is InputSource.FILE and spec.path is not None:
        text = _read_text(spec.path, source=spec.source)
        return SqlInput.file(text, spec.path)
    raise _input_failure("SQL 输入来源无效", DiagnosticErrorType.FILE_READ_ERROR, source=spec.source)


def _load_parameters(path: Path | None) -> ParameterDocument | None:
    if path is None:
        return None
    text = _read_text(path, source=InputSource.PARAMS_FILE)
    try:
        document = parse_json_document(text)
    except JsonDocumentError as exc:
        raise CliFailure(
            code=ErrorCode.INPUT_ERROR,
            message="参数文件不是有效 JSON",
            retryable=False,
            details=(
                ErrorDetail(
                    error_type=DiagnosticErrorType.INVALID_PARAMS_JSON,
                    argument="--params-file",
                    source=InputSource.PARAMS_FILE,
                    path=path,
                ),
            ),
            exit_code=ExitCode.INPUT_ERROR,
        ) from exc
    if is_json_object(document):
        return ParameterDocument(kind=ParameterKind.OBJECT, values=document, source=path)
    if is_json_array(document):
        return ParameterDocument(kind=ParameterKind.ARRAY, values=document, source=path)
    raise CliFailure(
        code=ErrorCode.INPUT_ERROR,
        message="参数文件顶层只能是 JSON object 或 array",
        retryable=False,
        details=(
            ErrorDetail(
                error_type=DiagnosticErrorType.INVALID_PARAMS_TYPE,
                argument="--params-file",
                source=InputSource.PARAMS_FILE,
                path=path,
            ),
        ),
        exit_code=ExitCode.INPUT_ERROR,
    )


def _read_text(path: Path, *, source: InputSource) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise CliFailure(
            code=ErrorCode.INPUT_ERROR,
            message="输入文件不存在",
            retryable=False,
            details=(ErrorDetail(error_type=DiagnosticErrorType.FILE_NOT_FOUND, source=source, path=path),),
            exit_code=ExitCode.INPUT_ERROR,
        ) from exc
    except UnicodeDecodeError as exc:
        raise CliFailure(
            code=ErrorCode.INPUT_ERROR,
            message="输入文件不是有效 UTF-8",
            retryable=False,
            details=(ErrorDetail(error_type=DiagnosticErrorType.FILE_DECODE_ERROR, source=source, path=path),),
            exit_code=ExitCode.INPUT_ERROR,
        ) from exc
    except OSError as exc:
        raise CliFailure(
            code=ErrorCode.INPUT_ERROR,
            message="输入文件读取失败",
            retryable=False,
            details=(ErrorDetail(error_type=DiagnosticErrorType.FILE_READ_ERROR, source=source, path=path),),
            exit_code=ExitCode.INPUT_ERROR,
        ) from exc


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
