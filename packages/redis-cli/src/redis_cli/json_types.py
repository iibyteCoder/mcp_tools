"""Named JSON boundary types used by persistence and presentation."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeAlias, TypedDict

JsonScalar: TypeAlias = str | int | float | bool | None
if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
    JsonOutput: TypeAlias = JsonValue | Mapping[str, object] | Sequence[object]
else:
    JsonValue: TypeAlias = object
    JsonOutput: TypeAlias = object


class SettingsDocument(TypedDict):
    host: str
    port: int
    username: str
    database: int
    connection_timeout: float
    tls: bool


class ProfileDocument(TypedDict):
    name: str
    settings: SettingsDocument
    description: str | None
    password_present: bool


class BindingDocument(TypedDict):
    path: str
    profile: str


class RegistryDocument(TypedDict):
    schema: str
    version: int
    profiles: list[ProfileDocument]
    bindings: list[BindingDocument]


class ErrorDocument(TypedDict, total=False):
    code: str
    message: str
    hint: str


class SuccessEnvelope(TypedDict):
    status: str
    profile: str | None
    data: JsonOutput


class FailureEnvelope(TypedDict):
    status: str
    profile: str | None
    error: ErrorDocument


class PingData(TypedDict):
    """Result of a Redis PING operation."""

    pong: bool


class FlushData(TypedDict):
    """Result of a Redis FLUSHDB operation."""

    flushed: bool


class ProfileView(TypedDict):
    """Secret-free profile data returned by profile commands."""

    name: str
    host: str
    port: int
    username: str
    database: int
    connection_timeout: float
    tls: bool
    description: str | None
    password_present: bool


class CurrentProfileView(ProfileView):
    """Profile view enriched with the directory that selected it."""

    path: str


class ConnectionStatusData(TypedDict):
    """Resolved non-secret connection settings."""

    source: str
    host: str
    port: int
    username: str
    database: int
    connection_timeout: float
    tls: bool
    password_present: bool


class KeyScanData(TypedDict):
    """One bounded Redis SCAN page."""

    keys: list[str]
    next_cursor: str | None


class KeyInspectionData(TypedDict):
    """Type, TTL and bounded preview for one Redis key."""

    key: str
    type: str
    ttl: int
    length: int
    preview_supported: bool
    preview: JsonValue
    truncated: bool


class KeyPageData(TypedDict):
    """One compatibility page over scan results."""

    keys: list[str]
    page: int
    page_size: int
    next_cursor: str | None


__all__ = [
    "BindingDocument",
    "ConnectionStatusData",
    "CurrentProfileView",
    "ErrorDocument",
    "FailureEnvelope",
    "FlushData",
    "JsonOutput",
    "JsonScalar",
    "JsonValue",
    "KeyInspectionData",
    "KeyPageData",
    "KeyScanData",
    "PingData",
    "ProfileDocument",
    "ProfileView",
    "RegistryDocument",
    "SettingsDocument",
    "SuccessEnvelope",
]
