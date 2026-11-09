"""Named JSON boundary types used by persistence and presentation."""

from __future__ import annotations

from typing import TypeAlias, TypedDict

from db_cli_kit.json_codec import JsonObject, JsonValue

JsonOutput: TypeAlias = JsonValue


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


class ErrorDocument(TypedDict):
    code: str
    message: str
    retryable: bool
    hint: str | None


class MetaDocument(TypedDict):
    command_group: str | None
    action: str | None
    profile: str | None
    output_mode: str


class SuccessEnvelope(TypedDict):
    ok: bool
    data: JsonOutput
    meta: MetaDocument


class FailureEnvelope(TypedDict):
    ok: bool
    error: ErrorDocument
    meta: MetaDocument


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


class ProfileCurrentData(TypedDict):
    """Outcome of ``profile current`` when no profile is selected."""

    profile: str | None
    path: str


class ProfileBindingData(TypedDict):
    """Directory binding created by ``profile select``, ``profile bind`` or ``use``."""

    profile: str
    path: str


class ProfileClearData(TypedDict):
    """Outcome of ``profile clear``."""

    cleared: bool
    path: str


class ProfileRemoveData(TypedDict):
    """Outcome of ``profile remove``."""

    removed: bool
    bindings_removed: int


class ProfileValidateData(TypedDict):
    """Outcome of ``profile validate``."""

    validated: bool
    pong: bool


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


class SkillPathsData(TypedDict):
    """Global Codex and DSH Skill document paths."""

    codex: str
    dsh: str


__all__ = [
    "BindingDocument",
    "ConnectionStatusData",
    "CurrentProfileView",
    "ErrorDocument",
    "FailureEnvelope",
    "FlushData",
    "JsonObject",
    "JsonOutput",
    "JsonValue",
    "KeyInspectionData",
    "KeyPageData",
    "KeyScanData",
    "MetaDocument",
    "PingData",
    "ProfileBindingData",
    "ProfileClearData",
    "ProfileCurrentData",
    "ProfileDocument",
    "ProfileRemoveData",
    "ProfileValidateData",
    "ProfileView",
    "RegistryDocument",
    "SettingsDocument",
    "SkillPathsData",
    "SuccessEnvelope",
]
