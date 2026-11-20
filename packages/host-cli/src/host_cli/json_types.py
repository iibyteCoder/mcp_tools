"""Named JSON boundary types for the persisted registry and the envelopes."""

from __future__ import annotations

from typing import TypeAlias, TypedDict

from db_cli_kit.json_codec import JsonValue

JsonOutput: TypeAlias = JsonValue


class SettingsDocument(TypedDict):
    """Stored non-secret connection facts."""

    host: str
    user: str
    port: int
    description: str | None
    command_timeout: float


class ProfileDocument(TypedDict):
    """One stored profile."""

    name: str
    settings: SettingsDocument
    password_present: bool


class RegistryDocument(TypedDict):
    """The whole registry file."""

    tool: str
    profiles: list[ProfileDocument]


class StreamDocument(TypedDict, total=False):
    """One captured stream as rendered in JSON."""

    encoding: str
    text: str | None
    base64: str | None
    bytes: int
    dropped_bytes: int
    truncated: bool


class ErrorDocument(TypedDict, total=False):
    """The machine-readable failure payload.

    Optional keys carry evidence a consumer must act on -- which host key
    problem, which fingerprint, which words tripped the danger guard -- so no
    consumer ever has to parse the message text.
    """

    code: str
    message: str
    host_key_problem: str | None
    fingerprint: str | None
    danger_excerpts: list[str]


class SuccessEnvelope(TypedDict):
    """Rendered document for a successful invocation."""

    ok: bool
    data: JsonOutput
    error: None


class FailureEnvelope(TypedDict):
    """Rendered document for a failed invocation; ``data`` keeps any captured output."""

    ok: bool
    data: JsonOutput
    error: ErrorDocument


Envelope: TypeAlias = SuccessEnvelope | FailureEnvelope


__all__ = [
    "Envelope",
    "ErrorDocument",
    "FailureEnvelope",
    "JsonOutput",
    "ProfileDocument",
    "RegistryDocument",
    "SettingsDocument",
    "StreamDocument",
    "SuccessEnvelope",
]
