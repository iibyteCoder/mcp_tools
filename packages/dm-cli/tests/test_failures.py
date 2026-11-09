"""Tests for CLI error-code and failure mapping."""

from __future__ import annotations

from dm_cli.domain.command import DiagnosticErrorType, ErrorCode, ExitCode
from dm_cli.presentation.click.failures import client_failure
from dm_client.domain.errors import ComparisonError, ConfigurationError


def test_error_code_includes_configuration_and_comparison_failures() -> None:
    assert ErrorCode.CONFIGURATION_FAILED.value == "configuration_failed"
    assert ErrorCode.COMPARISON_FAILED.value == "comparison_failed"


def test_configuration_failure_has_an_unambiguous_code() -> None:
    failure = client_failure(ConfigurationError("configuration is invalid"))

    assert failure.code is ErrorCode.CONFIGURATION_FAILED
    assert failure.exit_code is ExitCode.EXECUTION_ERROR
    assert failure.details[0].error_type is DiagnosticErrorType.CONFIGURATION


def test_comparison_failure_has_an_unambiguous_code() -> None:
    failure = client_failure(ComparisonError(()))

    assert failure.code is ErrorCode.COMPARISON_FAILED
    assert failure.exit_code is ExitCode.EXECUTION_ERROR
    assert failure.details[0].error_type is DiagnosticErrorType.COMPARISON
