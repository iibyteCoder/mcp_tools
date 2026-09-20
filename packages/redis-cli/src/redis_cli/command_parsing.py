"""Strict parsing helpers for structured command arguments."""

from __future__ import annotations

import json

from redis_cli.enums import ErrorCode
from redis_cli.rendering import CliError
from redis_cli.values import PipelineCommand, PipelineRequest


def mapping_arguments(value: str, *, numeric: bool) -> tuple[str, ...]:
    """Convert a JSON object into Redis alternating key/value arguments."""

    try:
        loaded: object = json.loads(value)
    except ValueError as exc:
        raise CliError(ErrorCode.INVALID_ARGUMENT, "mapping must be valid JSON") from exc
    if not isinstance(loaded, dict) or not loaded:
        raise CliError(ErrorCode.INVALID_ARGUMENT, "mapping must be a non-empty JSON object")
    arguments: list[str] = []
    for key, item in loaded.items():
        if not isinstance(key, str) or not isinstance(item, (str, int, float)) or isinstance(item, bool):
            raise CliError(ErrorCode.INVALID_ARGUMENT, "mapping values must be strings or numbers")
        if numeric and not isinstance(item, (int, float)):
            raise CliError(ErrorCode.INVALID_ARGUMENT, "sorted-set scores must be numbers")
        arguments.extend((key, str(item)))
    return tuple(arguments)


def pipeline_request(value: object) -> PipelineRequest:
    """Validate a JSON array of Redis command arrays."""

    if not isinstance(value, list):
        raise CliError(ErrorCode.INVALID_ARGUMENT, "commands must be a JSON array")
    commands: list[PipelineCommand] = []
    for item in value:
        if not isinstance(item, list) or not item or not all(isinstance(part, str) for part in item):
            raise CliError(ErrorCode.INVALID_ARGUMENT, "each command must be a non-empty string array")
        commands.append(PipelineCommand(name=item[0], arguments=tuple(item[1:])))
    if not commands:
        raise CliError(ErrorCode.INVALID_ARGUMENT, "commands must not be empty")
    return PipelineRequest(commands=tuple(commands))


__all__ = ["mapping_arguments", "pipeline_request"]
