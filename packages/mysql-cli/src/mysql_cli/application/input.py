"""Typed loading and validation of SQL and parameter input documents."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mysql_cli.application.errors import CliFailure, ErrorDetail
from mysql_cli.domain.command import (
    CommandRequest,
    DiagnosticErrorType,
    ErrorCode,
    ExitCode,
    InputSource,
    ParameterKind,
    SqlInputSpec,
)
from mysql_cli.shared.json_codec import (
    JsonArray,
    JsonDocumentError,
    JsonObject,
    is_json_array,
    is_json_object,
    parse_json_document,
)
from mysql_client import DatabaseParameters, DatabaseValue, SqlInput


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

    @property
    def bindings(self) -> DatabaseParameters:
        """Return validated DB-API positional or named parameter bindings."""

        if self.kind is ParameterKind.ARRAY:
            if not isinstance(self.values, list):
                raise TypeError("数组参数文档类型无效")
            return tuple(_database_value(item) for item in self.values)
        if not isinstance(self.values, dict):
            raise TypeError("对象参数文档类型无效")
        return {key: _database_value(value) for key, value in self.values.items()}


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

    sql = _load_sql(request, stdin_text=stdin_text)
    parameters = _load_parameters(request.params_file)
    left_sql = _load_sql_spec(request.compare_left_sql_input, stdin_text=stdin_text)
    right_sql = _load_sql_spec(request.compare_right_sql_input, stdin_text=stdin_text)
    left_parameters = _load_parameters(request.compare_left_params_file)
    right_parameters = _load_parameters(request.compare_right_params_file)
    return LoadedInputs(
        sql=sql,
        parameters=parameters,
        compare_left_sql=left_sql,
        compare_right_sql=right_sql,
        compare_left_parameters=left_parameters,
        compare_right_parameters=right_parameters,
    )


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


def _load_sql_spec(spec: SqlInputSpec | None, *, stdin_text: str | None) -> SqlInput | None:
    if spec is None:
        return None
    source = spec.source
    text = spec.text
    path = spec.path
    if source is InputSource.INLINE:
        if not isinstance(text, str):
            raise _input_failure("比较内联 SQL 输入不完整", DiagnosticErrorType.FILE_READ_ERROR, source=source)
        return SqlInput.inline(text)
    if source is InputSource.STDIN:
        if stdin_text is None:
            raise _input_failure("未提供标准输入 SQL", DiagnosticErrorType.FILE_READ_ERROR, source=source)
        return SqlInput.stdin(stdin_text)
    if source is InputSource.FILE and isinstance(path, Path):
        return SqlInput.file(_read_text(path, source=source), path)
    raise _input_failure("比较 SQL 输入来源无效", DiagnosticErrorType.FILE_READ_ERROR, source=source)


def _database_value(value: object) -> DatabaseValue:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, list):
        return [_database_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _database_value(item) for key, item in value.items()}
    raise TypeError(f"参数值类型无效: {type(value).__name__}")


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
