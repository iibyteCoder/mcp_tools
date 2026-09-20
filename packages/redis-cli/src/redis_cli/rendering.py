"""JSON result envelopes and stable CLI error rendering."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import click

from redis_cli.enums import ErrorCode, ResultStatus

if TYPE_CHECKING:
    from redis_cli.json_types import ErrorDocument, FailureEnvelope, JsonOutput, SuccessEnvelope


class CliError(RuntimeError):
    """An expected command-boundary failure."""

    def __init__(self, code: ErrorCode, message: str, *, hint: str | None = None, exit_code: int = 2) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint
        self.exit_code = exit_code


def emit_success(profile: str | None, data: JsonOutput) -> None:
    """Write one compact success document."""

    envelope: SuccessEnvelope = {
        "status": ResultStatus.SUCCESS.value,
        "profile": profile,
        "data": data,
    }
    click.echo(json.dumps(envelope, ensure_ascii=False, separators=(",", ":")))


def emit_failure(profile: str | None, error: CliError) -> int:
    """Write one stable error document and return its process code."""

    details: ErrorDocument = {"code": error.code.value, "message": error.message}
    if error.hint is not None:
        details["hint"] = error.hint
    envelope: FailureEnvelope = {
        "status": ResultStatus.ERROR.value,
        "profile": profile,
        "error": details,
    }
    click.echo(json.dumps(envelope, ensure_ascii=False, separators=(",", ":")))
    return error.exit_code


__all__ = ["CliError", "emit_failure", "emit_success"]
