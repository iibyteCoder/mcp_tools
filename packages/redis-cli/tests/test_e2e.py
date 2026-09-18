from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from uuid import uuid4


def _resolve_cli() -> list[str]:
    installed = shutil.which("db-redis")
    if installed:
        return [installed]
    if os.getenv("DB_CLI_FORCE_INSTALLED") == "1":
        raise RuntimeError("db-redis is not installed")
    return [sys.executable, "-m", "redis_cli"]


def _run(arguments: list[str]) -> dict:
    result = subprocess.run(_resolve_cli() + arguments, capture_output=True, text=True, timeout=15, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


def test_installed_help() -> None:
    result = subprocess.run([*_resolve_cli(), "--help"], capture_output=True, text=True, timeout=10, check=False)

    assert result.returncode == 0
    assert "Commands:" in result.stdout


def test_real_redis_database_isolation_and_round_trip() -> None:
    key = f"_db_cli_test_{uuid4().hex}"
    first_database = "14"
    second_database = "15"
    try:
        set_result = _run(["--db", first_database, "--json", "string", "set", "--key", key, "--value", "db14"])
        missing_result = _run(["--db", second_database, "--json", "string", "get", "--key", key])
        switch_result = _run(["--db", first_database, "--json", "string", "get", "--key", key])

        assert set_result["data"]["ok"] is True
        assert missing_result["data"]["value"] is None
        assert switch_result["data"]["value"] == "db14"
    finally:
        for database in (first_database, second_database):
            _run(["--db", database, "--json", "key", "delete", "--keys", key])


def test_installed_pipeline_inspect_and_scan(tmp_path) -> None:
    prefix = f"_db_cli_efficiency_{uuid4().hex}"
    keys = [f"{prefix}:{suffix}" for suffix in ("string", "list", "hash")]
    base = ["--db", "14", "--json"]
    path = tmp_path / "commands.json"
    try:
        _run([*base, "string", "set", "--key", keys[0], "--value", "abcdef"])
        _run([*base, "list", "lpush", "--key", keys[1], "--values", "one", "--values", "two"])
        _run([*base, "hash", "hset", "--key", keys[2], "--mapping", '{"field":"value"}'])
        path.write_text(
            json.dumps(
                [
                    ["EXISTS", keys[0]],
                    ["GET", keys[0]],
                    ["LRANGE", keys[1], "0", "1"],
                    ["HGETALL", keys[2]],
                ]
            ),
            encoding="utf-8",
        )
        payload = _run([*base, "server", "pipeline", "--commands-file", str(path)])
        assert payload["data"] == {"results": [1, "abcdef", ["two", "one"], {"field": "value"}]}
        preview = _run([*base, "key", "inspect", "--key", keys[0], "--max-bytes", "3"])["data"]
        assert preview["preview"] == "abc" and preview["truncated"] is True
        assert preview["length"] == 6
        found = []
        cursor = None
        for _ in range(200):
            args = [*base, "key", "scan", "--pattern", f"{prefix}:*", "--limit", "2"]
            if cursor:
                args += ["--cursor", cursor]
            page = _run(args)["data"]
            assert len(page["keys"]) <= 2
            found.extend(page["keys"])
            cursor = page["next_cursor"]
            if cursor is None:
                break
        assert cursor is None
        assert set(found) == set(keys)
    finally:
        for key in keys:
            _run([*base, "key", "delete", "--keys", key])
