"""Translate raw dmPython exceptions into the typed DM client errors.

DM embeds a stable driver/server code in messages such as ``[CODE:-2007]``.
The translation never adds credentials or SQL text of its own; if the caller
knows the executed SQL it is scrubbed from the driver message before the error
is exposed.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Final

from dm_client.domain.errors import (
    AuthenticationError,
    ClientError,
    ConfigurationError,
    ConnectionError,
    ObjectNotFoundError,
    PermissionDeniedError,
    QueryError,
    QueryTimeoutError,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

_ERROR_CODE_PATTERN: Final[re.Pattern[str]] = re.compile(r"\[CODE:\s*(-?\d+)\]", re.IGNORECASE)
_REDACTED_SQL: Final[str] = "<sql>"
_REDACTED_SECRET: Final[str] = "<redacted>"

_PERMISSION_CODES: Final[frozenset[int]] = frozenset({-5504, -5512, -5595})
_OBJECT_NOT_FOUND_CODES: Final[frozenset[int]] = frozenset({-2106, -20008})
_SYNTAX_CODES: Final[frozenset[int]] = frozenset({-2007})

_TIMEOUT_MARKERS: Final[tuple[str, ...]] = (
    "timeout",
    "timed out",
    "time out",
    "超时",
)
_AUTHENTICATION_MARKERS: Final[tuple[str, ...]] = (
    "authentication",
    "authenticate",
    "login",
    "log in",
    "user name",
    "username",
    "password",
    "口令",
    "用户名",
    "认证",
    "登录",
)
_CONNECTION_MARKERS: Final[tuple[str, ...]] = (
    "connection",
    "connect",
    "network",
    "socket",
    "refused",
    "unreachable",
    "broken pipe",
    "连接",
    "网络",
)


def parse_error_code(message: str) -> int | None:
    """Return the signed DM driver code embedded in a message, if present."""

    match = _ERROR_CODE_PATTERN.search(message)
    if match is None:
        return None
    return int(match.group(1))


def translate_driver_error(
    exc: BaseException,
    *,
    sql: str | None = None,
    secrets: Sequence[str] = (),
) -> ClientError:
    """Map one raw driver exception to a safe typed client error."""

    message = _safe_message(exc, sql=sql, secrets=secrets)
    code = parse_error_code(message)
    hint = f"DM driver error code {code}" if code is not None else None

    if code in _PERMISSION_CODES:
        return PermissionDeniedError(message, hint=hint)
    if code in _OBJECT_NOT_FOUND_CODES:
        return ObjectNotFoundError(message, hint=hint)
    if code in _SYNTAX_CODES:
        return QueryError(message, hint=hint)

    folded = message.casefold()
    if _contains_marker(folded, _TIMEOUT_MARKERS):
        return QueryTimeoutError(message, hint=hint)
    if _contains_marker(folded, _AUTHENTICATION_MARKERS):
        return AuthenticationError(message, hint=hint)
    if _contains_marker(folded, _CONNECTION_MARKERS):
        return ConnectionError(message, hint=hint)
    return QueryError(message, hint=hint)


def translate_configuration_error(
    exc: BaseException,
    *,
    secrets: Sequence[str] = (),
) -> ClientError:
    """Translate a connection-argument failure, treating type errors as config."""

    if isinstance(exc, TypeError):
        return ConfigurationError(_safe_message(exc, sql=None, secrets=secrets))
    return translate_driver_error(exc, secrets=secrets)


def _safe_message(exc: BaseException, *, sql: str | None, secrets: Sequence[str]) -> str:
    message = str(exc).strip() or exc.__class__.__name__
    for secret in secrets:
        if secret:
            message = message.replace(secret, _REDACTED_SECRET)
    if sql is None:
        return message
    stripped_sql = sql.strip()
    if stripped_sql:
        message = message.replace(sql, _REDACTED_SQL).replace(stripped_sql, _REDACTED_SQL)
    return message


def _contains_marker(folded_message: str, markers: tuple[str, ...]) -> bool:
    return any(marker in folded_message for marker in markers)


__all__ = ["parse_error_code", "translate_configuration_error", "translate_driver_error"]
