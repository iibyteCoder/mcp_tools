"""Redis key inspection and lifecycle commands."""

from __future__ import annotations

from typing import cast

import click

from redis_cli.cli_support import (
    NONNEGATIVE_INT,
    emit_result,
    profile_text,
    run_command,
    runtime,
)
from redis_cli.constants import DEFAULT_PREVIEW_BYTE_LIMIT, DEFAULT_SCAN_LIMIT, MAX_SCAN_LIMIT
from redis_cli.enums import RedisCommand
from redis_cli.json_types import KeyPageData, KeyScanData
from redis_cli.rendering import emit_success


@click.group()
def key() -> None:
    """Inspect and manage Redis keys."""


@key.command("inspect")
@click.option("--key", "key_name", required=True)
@click.option("--limit", type=click.IntRange(min=1, max=MAX_SCAN_LIMIT), default=10, show_default=True)
@click.option("--max-bytes", type=NONNEGATIVE_INT, default=DEFAULT_PREVIEW_BYTE_LIMIT, show_default=True)
@click.pass_context
def key_inspect(ctx: click.Context, key_name: str, limit: int, max_bytes: int) -> None:
    """Return type, TTL, length, and a bounded preview."""

    current = runtime(ctx)
    emit_result(
        current.application.inspect_key(
            current.selected_profile,
            current.overrides,
            key=key_name,
            max_bytes=max_bytes,
            limit=limit,
        )
    )


@key.command("scan")
@click.option("--pattern", default="*", show_default=True)
@click.option("--cursor", type=NONNEGATIVE_INT, default=0, show_default=True)
@click.option("--limit", type=click.IntRange(min=1, max=MAX_SCAN_LIMIT), default=DEFAULT_SCAN_LIMIT, show_default=True)
@click.pass_context
def key_scan(ctx: click.Context, pattern: str, cursor: int, limit: int) -> None:
    """Return one bounded SCAN page."""

    current = runtime(ctx)
    emit_result(
        current.application.scan(
            current.selected_profile, current.overrides, pattern=pattern, cursor=cursor, limit=limit
        )
    )


@key.command("keys")
@click.option("--pattern", default="*", show_default=True)
@click.option("--page", type=click.IntRange(min=1), default=1, show_default=True)
@click.option(
    "--page-size", type=click.IntRange(min=1, max=MAX_SCAN_LIMIT), default=DEFAULT_SCAN_LIMIT, show_default=True
)
@click.pass_context
def key_keys(ctx: click.Context, pattern: str, page: int, page_size: int) -> None:
    """Return a bounded compatibility page over SCAN results."""

    current = runtime(ctx)
    result = current.application.scan(
        current.selected_profile,
        current.overrides,
        pattern=pattern,
        cursor=0,
        limit=min(MAX_SCAN_LIMIT, page * page_size),
    )
    data = cast("KeyScanData", result.data)
    keys = data["keys"]
    start = (page - 1) * page_size
    page_data = KeyPageData(
        keys=keys[start : start + page_size],
        page=page,
        page_size=page_size,
        next_cursor=data["next_cursor"],
    )
    emit_success(profile_text(result.profile), page_data)


@key.command("delete")
@click.option("--key", "keys", multiple=True, required=True)
@click.pass_context
def key_delete(ctx: click.Context, keys: tuple[str, ...]) -> None:
    """Delete one or more keys."""

    run_command(ctx, RedisCommand.DEL, keys)


@key.command("exists")
@click.option("--key", "key_name", required=True)
@click.pass_context
def key_exists(ctx: click.Context, key_name: str) -> None:
    """Check whether a key exists."""

    run_command(ctx, RedisCommand.EXISTS, (key_name,))


@key.command("type")
@click.option("--key", "key_name", required=True)
@click.pass_context
def key_type_command(ctx: click.Context, key_name: str) -> None:
    """Return a key's Redis type."""

    run_command(ctx, RedisCommand.TYPE, (key_name,))


@key.command("ttl")
@click.option("--key", "key_name", required=True)
@click.pass_context
def key_ttl(ctx: click.Context, key_name: str) -> None:
    """Return a key's TTL in seconds."""

    run_command(ctx, RedisCommand.TTL, (key_name,))


@key.command("expire")
@click.option("--key", "key_name", required=True)
@click.option("--seconds", type=NONNEGATIVE_INT, required=True)
@click.pass_context
def key_expire(ctx: click.Context, key_name: str, seconds: int) -> None:
    """Set a key's TTL."""

    run_command(ctx, RedisCommand.EXPIRE, (key_name, str(seconds)))


@key.command("persist")
@click.option("--key", "key_name", required=True)
@click.pass_context
def key_persist(ctx: click.Context, key_name: str) -> None:
    """Remove a key's TTL."""

    run_command(ctx, RedisCommand.PERSIST, (key_name,))


@key.command("rename")
@click.option("--key", "key_name", required=True)
@click.option("--new-key", required=True)
@click.pass_context
def key_rename(ctx: click.Context, key_name: str, new_key: str) -> None:
    """Rename a key."""

    run_command(ctx, RedisCommand.RENAME, (key_name, new_key))


@key.command("random")
@click.pass_context
def key_random(ctx: click.Context) -> None:
    """Return a random key."""

    run_command(ctx, RedisCommand.RANDOMKEY, ())


__all__ = ["key"]
