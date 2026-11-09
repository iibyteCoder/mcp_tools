"""Unit tests for SQL and positional parameter input loading."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from dm_cli.application.errors import CliFailure
from dm_cli.application.input import STDIN_INPUT_NAME, load_inputs
from dm_cli.domain.command import (
    CommandAction,
    CommandGroup,
    CommandRequest,
    DiagnosticErrorType,
    ErrorCode,
    ExitCode,
    InputSource,
    ParameterKind,
    SqlInputSpec,
)

if TYPE_CHECKING:
    from pathlib import Path


def request_for(
    *,
    sql_input: SqlInputSpec | None = None,
    params_file: Path | None = None,
    compare_left_sql_input: SqlInputSpec | None = None,
    compare_right_sql_input: SqlInputSpec | None = None,
    compare_left_params_file: Path | None = None,
    compare_right_params_file: Path | None = None,
) -> CommandRequest:
    return CommandRequest(
        group=CommandGroup.SQL,
        action=CommandAction.READ,
        sql_input=sql_input,
        params_file=params_file,
        compare_left_sql_input=compare_left_sql_input,
        compare_right_sql_input=compare_right_sql_input,
        compare_left_params_file=compare_left_params_file,
        compare_right_params_file=compare_right_params_file,
    )


def failure_of(request: CommandRequest, *, stdin_text: str | None = None) -> CliFailure:
    with pytest.raises(CliFailure) as caught:
        load_inputs(request, stdin_text=stdin_text)
    return caught.value


def test_inline_sql_is_loaded_with_its_text() -> None:
    inputs = load_inputs(request_for(sql_input=SqlInputSpec.inline("SELECT 1")), stdin_text=None)

    assert inputs.sql is not None
    assert inputs.sql.text == "SELECT 1"
    assert inputs.sql.name is None
    assert inputs.parameters is None


def test_file_sql_is_loaded_with_its_path_as_provenance(tmp_path: Path) -> None:
    path = tmp_path / "query.sql"
    path.write_text("SELECT 2 FROM DUAL", encoding="utf-8")

    inputs = load_inputs(request_for(sql_input=SqlInputSpec.file(path)), stdin_text=None)

    assert inputs.sql is not None
    assert inputs.sql.text == "SELECT 2 FROM DUAL"
    assert inputs.sql.name == str(path)


def test_stdin_sql_is_loaded_from_the_captured_text() -> None:
    inputs = load_inputs(request_for(sql_input=SqlInputSpec.stdin()), stdin_text="SELECT 3 FROM DUAL")

    assert inputs.sql is not None
    assert inputs.sql.text == "SELECT 3 FROM DUAL"
    assert inputs.sql.name == STDIN_INPUT_NAME


def test_missing_stdin_text_is_an_input_failure() -> None:
    failure = failure_of(request_for(sql_input=SqlInputSpec.stdin()))

    assert failure.code is ErrorCode.INPUT_ERROR
    assert failure.exit_code is ExitCode.INPUT_ERROR
    assert failure.details[0].error_type is DiagnosticErrorType.FILE_READ_ERROR
    assert failure.details[0].source is InputSource.STDIN


def test_empty_inline_sql_is_invalid_sql() -> None:
    failure = failure_of(request_for(sql_input=SqlInputSpec.inline("")))

    assert failure.code is ErrorCode.INVALID_SQL
    assert failure.exit_code is ExitCode.INVALID_ARGUMENT
    assert failure.details[0].error_type is DiagnosticErrorType.SQL_PARSE


def test_blank_stdin_sql_is_invalid_sql() -> None:
    failure = failure_of(request_for(sql_input=SqlInputSpec.stdin()), stdin_text="  \n\t")

    assert failure.code is ErrorCode.INVALID_SQL
    assert failure.exit_code is ExitCode.INVALID_ARGUMENT
    assert failure.details[0].error_type is DiagnosticErrorType.SQL_PARSE
    assert failure.details[0].source is InputSource.STDIN


def test_missing_sql_file_is_an_input_failure(tmp_path: Path) -> None:
    failure = failure_of(request_for(sql_input=SqlInputSpec.file(tmp_path / "absent.sql")))

    assert failure.code is ErrorCode.INPUT_ERROR
    assert failure.exit_code is ExitCode.INPUT_ERROR
    assert failure.details[0].error_type is DiagnosticErrorType.FILE_NOT_FOUND
    assert failure.details[0].source is InputSource.FILE


def test_parameter_array_is_loaded_with_scalar_bindings(tmp_path: Path) -> None:
    path = tmp_path / "params.json"
    path.write_text('[1, "alpha", null, true, 1.5]', encoding="utf-8")

    inputs = load_inputs(request_for(params_file=path), stdin_text=None)

    assert inputs.parameters is not None
    assert inputs.parameters.kind is ParameterKind.ARRAY
    assert inputs.parameters.bindings == (1, "alpha", None, True, 1.5)
    assert inputs.parameters.count == 5
    assert inputs.parameters.source == path


@pytest.mark.parametrize("document", ['{"id": 1}', "42", '"text"', "null"])
def test_non_array_parameter_documents_are_rejected(tmp_path: Path, document: str) -> None:
    path = tmp_path / "params.json"
    path.write_text(document, encoding="utf-8")

    failure = failure_of(request_for(params_file=path))

    assert failure.code is ErrorCode.INPUT_ERROR
    assert failure.exit_code is ExitCode.INPUT_ERROR
    assert failure.details[0].error_type is DiagnosticErrorType.INVALID_PARAMS_TYPE
    assert "JSON array" in failure.message
    assert "?" in failure.message


def test_invalid_parameter_json_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "params.json"
    path.write_text("{not-json}", encoding="utf-8")

    failure = failure_of(request_for(params_file=path))

    assert failure.code is ErrorCode.INPUT_ERROR
    assert failure.exit_code is ExitCode.INPUT_ERROR
    assert failure.details[0].error_type is DiagnosticErrorType.INVALID_PARAMS_JSON


def test_missing_parameter_file_is_rejected(tmp_path: Path) -> None:
    failure = failure_of(request_for(params_file=tmp_path / "absent.json"))

    assert failure.code is ErrorCode.INPUT_ERROR
    assert failure.exit_code is ExitCode.INPUT_ERROR
    assert failure.details[0].error_type is DiagnosticErrorType.FILE_NOT_FOUND
    assert failure.details[0].source is InputSource.PARAMS_FILE


def test_non_utf8_parameter_file_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "params.json"
    path.write_bytes(b'["\xff"]')

    failure = failure_of(request_for(params_file=path))

    assert failure.code is ErrorCode.INPUT_ERROR
    assert failure.exit_code is ExitCode.INPUT_ERROR
    assert failure.details[0].error_type is DiagnosticErrorType.FILE_DECODE_ERROR


@pytest.mark.parametrize("document", ["[[1]]", '[{"id": 1}]'])
def test_nested_parameter_values_are_rejected(tmp_path: Path, document: str) -> None:
    path = tmp_path / "params.json"
    path.write_text(document, encoding="utf-8")

    failure = failure_of(request_for(params_file=path))

    assert failure.code is ErrorCode.INPUT_ERROR
    assert failure.exit_code is ExitCode.INPUT_ERROR
    assert failure.details[0].error_type is DiagnosticErrorType.INVALID_PARAMS_TYPE


def test_compare_left_and_right_sql_are_loaded() -> None:
    inputs = load_inputs(
        request_for(
            compare_left_sql_input=SqlInputSpec.inline("SELECT 1 AS ID"),
            compare_right_sql_input=SqlInputSpec.inline("SELECT 2 AS ID"),
        ),
        stdin_text=None,
    )

    assert inputs.sql is None
    assert inputs.compare_left_sql is not None
    assert inputs.compare_right_sql is not None
    assert inputs.compare_left_sql.text == "SELECT 1 AS ID"
    assert inputs.compare_right_sql.text == "SELECT 2 AS ID"


def test_compare_sql_files_preserve_their_paths(tmp_path: Path) -> None:
    left_path = tmp_path / "left.sql"
    right_path = tmp_path / "right.sql"
    left_path.write_text("SELECT 1 AS ID", encoding="utf-8")
    right_path.write_text("SELECT 2 AS ID", encoding="utf-8")

    inputs = load_inputs(
        request_for(
            compare_left_sql_input=SqlInputSpec.file(left_path),
            compare_right_sql_input=SqlInputSpec.file(right_path),
        ),
        stdin_text=None,
    )

    assert inputs.compare_left_sql is not None
    assert inputs.compare_right_sql is not None
    assert inputs.compare_left_sql.name == str(left_path)
    assert inputs.compare_right_sql.name == str(right_path)


def test_compare_parameter_files_are_loaded_independently(tmp_path: Path) -> None:
    left_params = tmp_path / "left.json"
    right_params = tmp_path / "right.json"
    left_params.write_text("[1]", encoding="utf-8")
    right_params.write_text('[2, "beta"]', encoding="utf-8")

    inputs = load_inputs(
        request_for(
            compare_left_sql_input=SqlInputSpec.inline("SELECT 1 AS ID FROM t WHERE ID = ?"),
            compare_right_sql_input=SqlInputSpec.inline("SELECT 2 AS ID FROM t WHERE ID = ? AND V = ?"),
            compare_left_params_file=left_params,
            compare_right_params_file=right_params,
        ),
        stdin_text=None,
    )

    assert inputs.compare_left_parameters is not None
    assert inputs.compare_right_parameters is not None
    assert inputs.compare_left_parameters.bindings == (1,)
    assert inputs.compare_right_parameters.bindings == (2, "beta")
    assert inputs.compare_left_parameters.source == left_params
    assert inputs.compare_right_parameters.source == right_params


def test_empty_compare_left_sql_reports_the_compare_argument() -> None:
    failure = failure_of(request_for(compare_left_sql_input=SqlInputSpec.inline("  ")))

    assert failure.code is ErrorCode.INVALID_SQL
    assert failure.exit_code is ExitCode.INVALID_ARGUMENT
    assert failure.details[0].error_type is DiagnosticErrorType.SQL_PARSE
    assert failure.details[0].argument == "--left-sql/--left-sql-file"


def test_missing_compare_file_is_an_input_failure(tmp_path: Path) -> None:
    failure = failure_of(request_for(compare_right_sql_input=SqlInputSpec.file(tmp_path / "absent.sql")))

    assert failure.code is ErrorCode.INPUT_ERROR
    assert failure.exit_code is ExitCode.INPUT_ERROR
    assert failure.details[0].error_type is DiagnosticErrorType.FILE_NOT_FOUND
