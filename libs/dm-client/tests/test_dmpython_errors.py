"""Unit tests for dmPython error-code parsing and typed mapping."""

from __future__ import annotations

import pytest

from dm_client.adapters.dmpython.errors import (
    parse_error_code,
    translate_configuration_error,
    translate_driver_error,
)
from dm_client.domain.errors import (
    AuthenticationError,
    ConfigurationError,
    ConnectionError,
    ObjectNotFoundError,
    PermissionDeniedError,
    QueryError,
    QueryTimeoutError,
)


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("[CODE:-5504] no privilege", -5504),
        ("prefix [CODE:-20008] suffix", -20008),
        ("[code:-2007] lowercase marker", -2007),
        ("no driver code here", None),
    ],
)
def test_parse_error_code(message: str, expected: int | None) -> None:
    assert parse_error_code(message) == expected


@pytest.mark.parametrize("code", [-5504, -5512, -5595])
def test_permission_codes_map_to_permission_denied(code: int) -> None:
    error = translate_driver_error(RuntimeError(f"[CODE:{code}] denied"))

    assert isinstance(error, PermissionDeniedError)
    assert f"{code}" in (error.hint or "")


@pytest.mark.parametrize("code", [-2106, -20008])
def test_missing_object_codes_map_to_object_not_found(code: int) -> None:
    error = translate_driver_error(RuntimeError(f"[CODE:{code}] missing"))

    assert isinstance(error, ObjectNotFoundError)


def test_syntax_code_maps_to_execution_failure() -> None:
    error = translate_driver_error(RuntimeError("[CODE:-2007] syntax error"))

    assert isinstance(error, QueryError)


@pytest.mark.parametrize(
    "message",
    [
        "authentication failed",
        "login failed",
        "用户名或口令错误",
    ],
)
def test_authentication_text_maps_to_authentication_error(message: str) -> None:
    assert isinstance(translate_driver_error(RuntimeError(message)), AuthenticationError)


@pytest.mark.parametrize(
    "message",
    [
        "connection refused",
        "network unreachable",
        "连接失败",
    ],
)
def test_connection_text_maps_to_connection_error(message: str) -> None:
    assert isinstance(translate_driver_error(RuntimeError(message)), ConnectionError)


@pytest.mark.parametrize(
    "message",
    [
        "query timeout",
        "statement timed out",
        "网络通信超时",
    ],
)
def test_timeout_text_maps_to_query_timeout(message: str) -> None:
    assert isinstance(translate_driver_error(RuntimeError(message)), QueryTimeoutError)


def test_unknown_failure_falls_back_to_query_error() -> None:
    error = translate_driver_error(RuntimeError("unexpected server failure"))

    assert isinstance(error, QueryError)


def test_driver_argument_type_error_maps_to_configuration_error() -> None:
    error = translate_configuration_error(
        TypeError("connection_timeout : expecting an Integer value.")
    )

    assert isinstance(error, ConfigurationError)
    assert isinstance(translate_driver_error(TypeError("unexpected")), QueryError)


def test_driver_message_is_preserved_and_sql_is_scrubbed() -> None:
    sql = "SELECT secret_column FROM secret_table"
    raw = RuntimeError(f"failed while running {sql} [CODE:-20007]")

    error = translate_driver_error(raw, sql=sql)

    assert "secret_column" not in error.message
    assert "secret_table" not in error.message
    assert "<sql>" in error.message
