"""Bounded Redis previews and opaque, lossless SCAN continuation."""

from __future__ import annotations

import json
import re
import time
from contextlib import suppress
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from platformdirs import user_cache_path

if TYPE_CHECKING:
    from pathlib import Path


async def scan_page(
    client: Any,
    pattern: str,
    limit: int,
    cursor: str | None,
    target: str,
    cache: Path | None = None,
) -> dict[str, Any]:
    directory = cache or user_cache_path("db-cli", appauthor=False) / "redis-scan"
    if not cursor and directory.exists():
        for entry in directory.glob("*.json"):
            with suppress(OSError):
                if entry.stat().st_mtime < time.time() - 86400:
                    entry.unlink()
    state: dict[str, Any] = {"position": 0, "pending": [], "target": target, "pattern": pattern}
    if cursor:
        if not re.fullmatch(r"[0-9a-f]{32}", cursor):
            raise ValueError("无效游标, 请重新开始 key scan")
        path = directory / f"{cursor}.json"
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
            if state["expires"] < time.time():
                path.unlink(missing_ok=True)
                raise ValueError("游标已过期, 请重新开始 key scan")
            if state["target"] != target or state["pattern"] != pattern:
                raise ValueError("游标与当前连接或 pattern 不匹配")
        except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError("游标不存在或损坏, 请重新开始 key scan") from exc
    pending = state["pending"]
    if not pending and (not cursor or state["position"] != 0):
        position, pending = await client.scan(cursor=state["position"], match=pattern, count=limit)
        state["position"] = position
    rows, state["pending"] = pending[:limit], pending[limit:]
    next_cursor = None
    if state["pending"] or state["position"] != 0:
        directory.mkdir(parents=True, exist_ok=True)
        next_cursor = uuid4().hex
        state["expires"] = time.time() + 86400
        # Unique immutable files keep concurrent consumers from corrupting state.
        temporary = directory / f"{next_cursor}.tmp"
        temporary.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        temporary.replace(directory / f"{next_cursor}.json")
    return {"keys": rows, "next_cursor": next_cursor}


async def inspect_key(client: Any, key: str, limit: int, max_bytes: int) -> dict[str, Any]:
    kind = await client.type(key)
    if kind == "none":
        return {"type": "none", "ttl": -2}
    result: dict[str, Any] = {"type": kind, "ttl": await client.ttl(key)}
    if kind == "string":
        length = await client.strlen(key)
        preview = await client.execute_command("GETRANGE", key, 0, max_bytes - 1, NEVER_DECODE=True)
        if isinstance(preview, bytes):
            preview = preview.decode("utf-8", errors="replace")
        result.update(length=length, preview=preview, truncated=length > max_bytes)
        return result
    if kind == "list":
        length = await client.llen(key)
        preview = await client.lrange(key, 0, limit - 1)
    elif kind == "zset":
        length = await client.zcard(key)
        preview = await client.zrange(key, 0, limit - 1, withscores=True)
    elif kind == "hash":
        length = await client.hlen(key)
        _, values = await client.hscan(key, cursor=0, count=limit)
        preview = list(values.items())[:limit]
    elif kind == "set":
        length = await client.scard(key)
        _, values = await client.sscan(key, cursor=0, count=limit)
        preview = values[:limit]
    else:
        # Streams and module-defined types have no generic safe preview.
        result["preview_supported"] = False
        return result
    truncated = length > len(preview)

    def clip(value: Any) -> Any:
        nonlocal truncated
        if isinstance(value, str):
            raw = value[:max_bytes].encode("utf-8")
            if len(value) > max_bytes or len(raw) > max_bytes:
                truncated = True
                return raw[:max_bytes].decode("utf-8", errors="replace")
        if isinstance(value, (list, tuple)):
            return [clip(item) for item in value]
        return value

    result.update(length=length, preview=clip(preview))
    result["truncated"] = truncated
    return result
