"""Translate application, client and Click failures into CLI envelopes."""

from __future__ import annotations

from typing import TYPE_CHECKING

import click

from mysql_cli.application.errors import CliFailure, ErrorDetail
from mysql_cli.application.profile import ProfileServiceError, ProfileServiceErrorCode
from mysql_cli.domain.command import DiagnosticErrorType, ErrorCode, ExitCode
from mysql_cli.domain.profile import RegistryErrorCode
from mysql_client import ClientError, error_report_from_exception
from mysql_client import ErrorCode as ClientErrorCode

if TYPE_CHECKING:
    from mysql_cli.ports.profile_store import ProfileStoreError


def argument_failure(
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


def click_failure(error: click.ClickException) -> CliFailure:
    message = error.message or str(error)
    if message.startswith("No such command "):
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
    message = message or "command argument is invalid"
    argument_name = argument_name_for(argument) or "command"
    return argument_failure(message, argument_name)


def argument_name_for(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, tuple) and all(isinstance(item, str) for item in value):
        return "/".join(value)
    return None


def cancelled_failure() -> CliFailure:
    return CliFailure(
        code=ErrorCode.CANCELLED,
        message="operation cancelled",
        retryable=False,
        details=(ErrorDetail(error_type=DiagnosticErrorType.CANCELLED),),
        exit_code=ExitCode.EXECUTION_ERROR,
    )


def internal_failure() -> CliFailure:
    return CliFailure(
        code=ErrorCode.INTERNAL_ERROR,
        message="internal error",
        retryable=False,
        details=(ErrorDetail(error_type=DiagnosticErrorType.EXECUTION),),
        exit_code=ExitCode.INTERNAL_ERROR,
    )


def profile_store_failure(error: ProfileStoreError) -> CliFailure:
    mapping = {
        RegistryErrorCode.CORRUPT: (ErrorCode.PROFILE_REGISTRY_CORRUPT, DiagnosticErrorType.PROFILE_REGISTRY_CORRUPT),
        RegistryErrorCode.UNSUPPORTED_VERSION: (
            ErrorCode.PROFILE_REGISTRY_VERSION,
            DiagnosticErrorType.PROFILE_REGISTRY_VERSION,
        ),
        RegistryErrorCode.LOCKED: (ErrorCode.PROFILE_REGISTRY_LOCKED, DiagnosticErrorType.PROFILE_REGISTRY_LOCKED),
        RegistryErrorCode.IO: (ErrorCode.INPUT_ERROR, DiagnosticErrorType.FILE_READ_ERROR),
    }
    code, error_type = mapping.get(
        error.code,
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


def profile_service_failure(error: ProfileServiceError) -> CliFailure:
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


def client_failure(error: ClientError) -> CliFailure:
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


__all__ = [
    "argument_failure",
    "argument_name_for",
    "cancelled_failure",
    "click_failure",
    "client_failure",
    "internal_failure",
    "profile_service_failure",
    "profile_store_failure",
]
