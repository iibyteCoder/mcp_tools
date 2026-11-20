"""JSON envelopes and stable error rendering for every command.

This module is the only place that knows the wire shape. Domain objects are
turned into plain documents here, so a change to the envelope never reaches
into the domain and a domain change never silently alters the contract.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from db_cli_kit.json_codec import encode_json_document
from db_cli_kit.stdio import TEXT_ENCODING
from host_cli.domain.enums import AuditWriteStatus, ErrorCode, ExitCode, StreamEncoding
from host_cli.domain.errors import HostCliError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from host_cli.domain.models import (
        GatePrediction,
        ProfileRecord,
        ProfileView,
        RunResult,
        StreamCapture,
    )
    from host_cli.infrastructure.approvals import Approval
    from host_cli.json_types import Envelope, ErrorDocument, JsonOutput


def success_envelope(data: JsonOutput) -> Envelope:
    """Wrap a success payload in the one envelope shape every command returns."""

    return {"ok": True, "data": data, "error": None}


def failure_envelope(data: JsonOutput | None, error: HostCliError) -> Envelope:
    """Wrap a failure, keeping any captured output available to the caller.

    ``data`` survives a failure on purpose: when a remote command exits non-zero
    or times out, its output is exactly what the operator needs to look at.
    """

    return {"ok": False, "data": data, "error": error_document(error)}


def profile_document(view: ProfileView) -> JsonOutput:
    """Render one profile without any secret material."""

    return {
        "name": view.name.value,
        "host": view.settings.host,
        "user": view.settings.user,
        "port": view.settings.port,
        "description": view.settings.description,
        "command_timeout": view.settings.command_timeout,
        "read_only": view.settings.read_only,
        "max_commands_per_minute": view.settings.max_commands_per_minute,
        "requires_approval": view.settings.requires_approval,
        "password_present": view.password_present,
    }


def profiles_document(views: Sequence[ProfileView]) -> JsonOutput:
    """Render the profile list."""

    return {"profiles": [profile_document(view) for view in views]}


def approval_document(approval: Approval) -> JsonOutput:
    """Render an issued approval.

    The digest is included but not the command: an approval record must not carry
    a copy of what is about to run, and the digest is what the token is checked
    against anyway.
    """

    return {
        "approved": True,
        "profile": approval.profile,
        "token": approval.token,
        "command_digest": approval.command_digest,
        "issued_at": approval.issued_at.isoformat(),
        "expires_at": approval.expires_at.isoformat(),
        "instruction": ("pass this token with --approve to run exactly this command on this profile before it expires"),
    }


def dry_run_document(
    *,
    record: ProfileRecord,
    command: str,
    prediction: GatePrediction,
    audit_status: AuditWriteStatus,
) -> JsonOutput:
    """Render a probe: what every gate decided, and what would have happened.

    Deliberately shaped like ``run_document`` minus the output fields, so a
    caller can use one code path for both and read ``dry_run`` to tell them
    apart.

    ``would_block`` covers **all** the gates, not just the danger guard. A probe
    that answered only the danger question would report green for a command the
    profile is configured to refuse, which is worse than no probe at all:
    ``refused_by`` names the gate so the caller can act on it.
    """

    return {
        "dry_run": True,
        "profile": record.name.value,
        "command": command,
        "host": record.settings.host,
        "user": record.settings.user,
        "verdict": prediction.report.verdict.value,
        "would_block": prediction.would_block,
        "refused_by": None if prediction.reason is None else prediction.reason.value,
        "danger_categories": [category.value for category in prediction.report.categories],
        "danger_excerpts": [finding.excerpt for finding in prediction.report.findings],
        "audit": audit_status.value,
    }


def run_document(result: RunResult, *, audit_status: AuditWriteStatus) -> JsonOutput:
    """Render one invocation, including the evidence that survived classification.

    ``audit_status`` is reported because the command has already run by the time
    its line is written: a caller that cannot see a missing record must not be
    left believing the trail is complete.
    """

    return {
        "profile": result.profile.value,
        "command": result.command,
        "outcome": result.outcome.kind.value,
        "remote_exit_code": result.remote_exit_code,
        "remote_state": result.remote_state.value,
        "duration_ms": result.duration_ms,
        "fingerprint": result.fingerprint,
        "forced": result.forced,
        "danger_categories": [category.value for category in result.danger_categories],
        "audit": audit_status.value,
        "stdout": _stream_document(result.stdout),
        "stderr": _stream_document(result.stderr),
        "debug_log_tail": list(result.debug_log_tail),
    }


def error_document(error: HostCliError) -> ErrorDocument:
    """Render the machine-readable failure payload.

    Failure evidence a consumer must act on -- which host key problem, what
    fingerprint was seen, which words tripped the danger guard -- is exposed as
    its own field, never as prose.
    """

    document: ErrorDocument = {"code": error.code.value, "message": error.message}
    if error.host_key_problem is not None:
        document["host_key_problem"] = error.host_key_problem.value
    if error.fingerprint is not None:
        document["fingerprint"] = error.fingerprint
    if error.danger_excerpts:
        document["danger_excerpts"] = list(error.danger_excerpts)
    return document


def emit(envelope: Envelope) -> None:
    """Write one envelope to stdout as UTF-8 bytes.

    The process-wide stream reconfigure already guarantees UTF-8; writing bytes
    as well means a future change to that call cannot silently mangle output.
    """

    sys.stdout.buffer.write(encode_json_document(envelope).encode(TEXT_ENCODING))
    sys.stdout.buffer.flush()


def exit_code_for(ok: bool) -> ExitCode:
    """Return the process exit code for a finished command."""

    return ExitCode.OK if ok else ExitCode.FAILURE


def argument_error(message: str) -> HostCliError:
    """Wrap a command-line parsing failure in the shared error type."""

    return HostCliError(ErrorCode.INVALID_ARGUMENT, message)


def _stream_document(stream: StreamCapture) -> JsonOutput:
    """Render one captured stream as text or base64, never both."""

    payload: JsonOutput = (
        {"base64": stream.base64} if stream.encoding is StreamEncoding.BINARY else {"text": stream.text}
    )
    base: JsonOutput = {
        "encoding": stream.encoding.value,
        "bytes": stream.bytes,
        "dropped_bytes": stream.dropped_bytes,
        "truncated": stream.truncated,
    }
    assert isinstance(base, dict) and isinstance(payload, dict)
    base.update(payload)
    return base


__all__ = [
    "argument_error",
    "dry_run_document",
    "emit",
    "error_document",
    "exit_code_for",
    "failure_envelope",
    "profile_document",
    "profiles_document",
    "run_document",
    "success_envelope",
]
