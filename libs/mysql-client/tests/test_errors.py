import pytest

from mysql_client.enums import ErrorCode, ExitCode
from mysql_client.errors import (
    AuthenticationError,
    ClientError,
    QueryCancelledError,
    QueryTimeoutError,
    SqlParseError,
    error_report_from_exception,
    exit_code_for_error,
)
from mysql_client.models import CliResponse


@pytest.mark.parametrize(
    ("error", "code", "exit_code"),
    [
        (SqlParseError("bad SQL"), ErrorCode.INVALID_SQL, ExitCode.INVALID_ARGUMENT),
        (AuthenticationError("denied"), ErrorCode.AUTHENTICATION_FAILED, ExitCode.AUTHENTICATION_FAILED),
        (QueryTimeoutError("slow", hint="check indexes"), ErrorCode.TIMEOUT, ExitCode.TIMEOUT),
        (QueryCancelledError("cancelled"), ErrorCode.CANCELLED, ExitCode.CANCELLED),
    ],
)
def test_error_hierarchy_maps_to_stable_codes(error: ClientError, code: ErrorCode, exit_code: ExitCode) -> None:
    report = error_report_from_exception(error)

    assert report.code is code
    assert report.message == str(error)
    assert exit_code_for_error(report.code) is exit_code


def test_unexpected_and_builtin_errors_have_deterministic_mapping() -> None:
    invalid = error_report_from_exception(ValueError("bad argument"))
    unexpected = error_report_from_exception(RuntimeError("broken"))

    assert invalid.code is ErrorCode.INVALID_ARGUMENT
    assert unexpected.code is ErrorCode.INTERNAL_ERROR
    assert exit_code_for_error(unexpected.code) is ExitCode.INTERNAL_ERROR


def test_cli_failure_carries_the_report_exit_code() -> None:
    report = error_report_from_exception(QueryTimeoutError("slow"))

    response = CliResponse.failure(report)

    assert response.exit_code is ExitCode.TIMEOUT
    assert response.error == report
