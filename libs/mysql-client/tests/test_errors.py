import pytest

from mysql_client.domain.enums import ErrorCode
from mysql_client.domain.errors import (
    AuthenticationError,
    ClientError,
    QueryCancelledError,
    QueryTimeoutError,
    SqlParseError,
    error_report_from_exception,
)


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (SqlParseError("bad SQL"), ErrorCode.INVALID_SQL),
        (AuthenticationError("denied"), ErrorCode.AUTHENTICATION_FAILED),
        (QueryTimeoutError("slow", hint="check indexes"), ErrorCode.TIMEOUT),
        (QueryCancelledError("cancelled"), ErrorCode.CANCELLED),
    ],
)
def test_error_hierarchy_maps_to_stable_domain_codes(error: ClientError, code: ErrorCode) -> None:
    report = error_report_from_exception(error)

    assert report.code is code
    assert report.message == str(error)
    assert report.hint == error.hint


def test_error_report_has_no_cli_exit_or_presentation_policy() -> None:
    report = error_report_from_exception(QueryTimeoutError("slow"))

    assert report.code is ErrorCode.TIMEOUT
    assert not hasattr(report, "exit_code")
    assert not hasattr(report, "output_format")


def test_unexpected_and_builtin_errors_have_deterministic_mapping() -> None:
    invalid = error_report_from_exception(ValueError("bad argument"))
    unexpected = error_report_from_exception(RuntimeError("broken"))

    assert invalid.code is ErrorCode.INVALID_ARGUMENT
    assert unexpected.code is ErrorCode.INTERNAL_ERROR
