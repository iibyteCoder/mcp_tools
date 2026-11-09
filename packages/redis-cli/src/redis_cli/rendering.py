"""JSON result envelopes and stable CLI error rendering."""

from __future__ import annotations

from typing import TYPE_CHECKING

import click

from db_cli_kit.json_codec import encode_json_document
from redis_cli.enums import ErrorCode, OutputMode
from redis_cli.json_types import MetaDocument

if TYPE_CHECKING:
    from redis_cli.command_meta import CommandMeta
    from redis_cli.domain.errors import RedisCliError
    from redis_cli.json_types import ErrorDocument, FailureEnvelope, JsonOutput, SuccessEnvelope


_EXIT_CODES: dict[ErrorCode, int] = {
    ErrorCode.INVALID_ARGUMENT: 2,
    ErrorCode.PROFILE_NOT_FOUND: 4,
    ErrorCode.PROFILE_CONFLICT: 4,
    ErrorCode.PROFILE_REGISTRY: 4,
    ErrorCode.SECRET_STORE: 4,
    ErrorCode.AUTH_FAILED: 5,
    ErrorCode.CONNECTION_FAILED: 5,
    ErrorCode.TIMEOUT: 5,
    ErrorCode.EXECUTION_FAILED: 5,
    ErrorCode.CANCELLED: 5,
    ErrorCode.INTERNAL_ERROR: 70,
}


def emit_success(data: JsonOutput, meta: CommandMeta) -> None:
    """Write one compact success document."""

    envelope: SuccessEnvelope = {
        "ok": True,
        "data": data,
        "meta": _meta_document(meta),
    }
    click.echo(encode_json_document(envelope), nl=False)


def emit_failure(error: RedisCliError, meta: CommandMeta) -> int:
    """Write one stable error document and return its process code."""

    details: ErrorDocument = {
        "code": error.code.value,
        "message": error.message,
        "retryable": error.retryable,
        "hint": error.hint,
    }
    envelope: FailureEnvelope = {
        "ok": False,
        "error": details,
        "meta": _meta_document(meta),
    }
    click.echo(encode_json_document(envelope), nl=False)
    return exit_code_for(error.code)


def exit_code_for(code: ErrorCode) -> int:
    """Map one stable error category to its process exit code."""

    return _EXIT_CODES[code]


def _meta_document(meta: CommandMeta) -> MetaDocument:
    return MetaDocument(
        command_group=None if meta.group is None else meta.group.value,
        action=meta.action,
        profile=None if meta.profile is None else meta.profile.value,
        output_mode=OutputMode.JSON.value,
    )


__all__ = ["emit_failure", "emit_success", "exit_code_for"]
