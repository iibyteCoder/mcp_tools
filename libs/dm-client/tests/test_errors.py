"""Unit tests for the typed DM client error hierarchy."""

from __future__ import annotations

from dm_client.domain.enums import WriteOutcome
from dm_client.domain.errors import (
    AuthenticationError,
    ClientError,
    ClientErrorCode,
    ConfigurationError,
    ConnectionError,
    ObjectNotFoundError,
    PermissionDeniedError,
    QueryError,
    QueryTimeoutError,
    UnsupportedObjectError,
    WriteError,
    error_report_from_exception,
)


def test_client_errors_expose_stable_codes() -> None:
    expected = {
        ConfigurationError: ClientErrorCode.CONFIGURATION_FAILED,
        ConnectionError: ClientErrorCode.CONNECTION_FAILED,
        AuthenticationError: ClientErrorCode.AUTHENTICATION_FAILED,
        PermissionDeniedError: ClientErrorCode.PERMISSION_DENIED,
        ObjectNotFoundError: ClientErrorCode.OBJECT_NOT_FOUND,
        UnsupportedObjectError: ClientErrorCode.UNSUPPORTED_OBJECT,
        QueryError: ClientErrorCode.EXECUTION_FAILED,
        QueryTimeoutError: ClientErrorCode.TIMEOUT,
    }

    for error_type, code in expected.items():
        assert issubclass(error_type, ClientError)
        assert error_type("failure").code is code


def test_write_error_carries_the_transaction_outcome() -> None:
    error = WriteError("commit failed", outcome=WriteOutcome.UNKNOWN)

    report = error_report_from_exception(error)

    assert report.code is ClientErrorCode.EXECUTION_FAILED
    assert report.write_outcome is WriteOutcome.UNKNOWN
    assert report.exception_type == "WriteError"


def test_error_report_from_value_error_is_invalid_argument() -> None:
    assert error_report_from_exception(ValueError("bad")).code is ClientErrorCode.INVALID_ARGUMENT


def test_error_report_from_unexpected_error_is_internal() -> None:
    report = error_report_from_exception(RuntimeError("boom"))

    assert report.code is ClientErrorCode.INTERNAL_ERROR
    assert report.message == "boom"
