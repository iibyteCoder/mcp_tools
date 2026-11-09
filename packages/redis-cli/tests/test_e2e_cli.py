"""End-to-end coverage against a real Redis server in Docker."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict, cast

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
REDIS_IMAGE = "redis:7-alpine"
REDIS_CONTAINER_PORT = "6379/tcp"
COMMAND_TIMEOUT_SECONDS = 30
STARTUP_TIMEOUT_SECONDS = 30


class JsonDocument(TypedDict, total=False):
    """The stable top-level CLI document used by E2E assertions."""

    ok: bool
    data: object
    error: object
    meta: object


@dataclass(frozen=True, slots=True)
class RedisEndpoint:
    """Host endpoint exposed by the temporary Redis container."""

    host: str
    port: int

    @property
    def url(self) -> str:
        return f"redis://{self.host}:{self.port}/0"


@pytest.fixture(scope="module")
def redis_endpoint() -> Iterator[RedisEndpoint]:
    """Start an isolated Redis server and remove it after the module finishes."""

    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("Docker is required for Redis CLI E2E tests")

    started = subprocess.run(
        [docker, "run", "--detach", "--rm", "--publish", "127.0.0.1::6379", REDIS_IMAGE],
        capture_output=True,
        text=True,
        check=True,
        timeout=COMMAND_TIMEOUT_SECONDS,
    )
    container_id = started.stdout.strip()
    try:
        port = _published_port(docker, container_id)
        _wait_for_redis(docker, container_id)
        yield RedisEndpoint(host="127.0.0.1", port=port)
    finally:
        subprocess.run([docker, "rm", "--force", container_id], capture_output=True, text=True, check=False)


def _published_port(docker: str, container_id: str) -> int:
    result = subprocess.run(
        [docker, "port", container_id, REDIS_CONTAINER_PORT],
        capture_output=True,
        text=True,
        check=True,
        timeout=COMMAND_TIMEOUT_SECONDS,
    )
    match = re.search(r":(\d+)\s*$", result.stdout.strip())
    if match is None:
        raise RuntimeError(f"Docker did not publish Redis port: {result.stdout!r}")
    return int(match.group(1))


def _wait_for_redis(docker: str, container_id: str) -> None:
    deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        result = subprocess.run(
            [docker, "exec", container_id, "redis-cli", "ping"],
            capture_output=True,
            text=True,
            check=False,
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
        if result.returncode == 0 and result.stdout.strip() == "PONG":
            return
        time.sleep(0.25)
    raise TimeoutError("Redis container did not become ready")


def run_cli(endpoint: RedisEndpoint, *arguments: str) -> JsonDocument:
    """Run the installed project CLI and assert a successful JSON response."""

    command = [
        "uv",
        "run",
        "--project",
        "packages/redis-cli",
        "db-redis",
        "--json",
        "--url",
        endpoint.url,
        *arguments,
    ]
    result = subprocess.run(
        command,
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=COMMAND_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        raise AssertionError(f"CLI failed ({result.returncode}): {result.stdout}\n{result.stderr}")
    document = json.loads(result.stdout)
    if not isinstance(document, dict):
        raise AssertionError(f"CLI returned a non-object document: {document!r}")
    typed_document = cast("JsonDocument", document)
    assert typed_document["ok"] is True
    return typed_document


@pytest.mark.e2e
def test_all_redis_cli_command_groups_against_real_redis(redis_endpoint: RedisEndpoint) -> None:
    """Exercise connection, server, key and every supported Redis data group."""

    status_document = run_cli(redis_endpoint, "connection", "status")
    assert status_document["meta"] == {
        "command_group": "connection",
        "action": "status",
        "profile": None,
        "output_mode": "json",
    }
    assert run_cli(redis_endpoint, "connection", "connect")["ok"] is True
    ping_document = run_cli(redis_endpoint, "server", "ping")
    assert ping_document["data"] == {"pong": True}
    assert ping_document["meta"] == {
        "command_group": "server",
        "action": "ping",
        "profile": None,
        "output_mode": "json",
    }
    assert isinstance(run_cli(redis_endpoint, "server", "info")["data"], dict)
    assert run_cli(redis_endpoint, "server", "dbsize")["data"] == 0

    assert run_cli(redis_endpoint, "string", "set", "--key", "alpha", "--value", "one")["ok"] is True
    string_get = run_cli(redis_endpoint, "string", "get", "--key", "alpha")
    assert string_get["data"] == "one"
    assert string_get["meta"] == {
        "command_group": "string",
        "action": "get",
        "profile": None,
        "output_mode": "json",
    }
    assert run_cli(redis_endpoint, "string", "append", "--key", "alpha", "--value", "!")["data"] == 4
    assert run_cli(redis_endpoint, "string", "strlen", "--key", "alpha")["data"] == 4
    assert run_cli(redis_endpoint, "string", "incr", "--key", "counter", "--amount", "2")["data"] == 2
    assert run_cli(redis_endpoint, "string", "mset", "--mapping", '{"beta":"two","gamma":"three"}')
    assert run_cli(redis_endpoint, "string", "mget", "--key", "alpha", "--key", "beta")["data"] == ["one!", "two"]

    assert run_cli(redis_endpoint, "hash", "set", "--key", "profile", "--mapping", '{"name":"Ada","role":"admin"}')
    assert run_cli(redis_endpoint, "hash", "get", "--key", "profile", "--field", "name")["data"] == "Ada"
    assert run_cli(redis_endpoint, "hash", "getall", "--key", "profile")["ok"] is True
    assert run_cli(redis_endpoint, "hash", "exists", "--key", "profile", "--field", "role")["data"] == 1
    assert run_cli(redis_endpoint, "hash", "keys", "--key", "profile")["ok"] is True
    assert run_cli(redis_endpoint, "hash", "values", "--key", "profile")["ok"] is True
    assert run_cli(redis_endpoint, "hash", "length", "--key", "profile")["data"] == 2
    assert run_cli(redis_endpoint, "hash", "delete", "--key", "profile", "--field", "role")["data"] == 1

    assert run_cli(redis_endpoint, "list", "push", "--key", "queue", "--value", "first", "--value", "second")
    assert run_cli(redis_endpoint, "list", "range", "--key", "queue", "--start", "0", "--stop", "-1")["data"] == [
        "second",
        "first",
    ]
    assert run_cli(redis_endpoint, "list", "index", "--key", "queue", "--index", "0")["data"] == "second"
    assert run_cli(redis_endpoint, "list", "length", "--key", "queue")["data"] == 2
    assert run_cli(redis_endpoint, "list", "trim", "--key", "queue", "--start", "0", "--stop", "0")
    assert run_cli(redis_endpoint, "list", "pop", "--key", "queue")["data"] == "second"

    assert run_cli(redis_endpoint, "set", "add", "--key", "tags", "--member", "one", "--member", "two")
    assert run_cli(redis_endpoint, "set", "is-member", "--key", "tags", "--member", "one")["data"] == 1
    assert run_cli(redis_endpoint, "set", "members", "--key", "tags")["ok"] is True
    assert run_cli(redis_endpoint, "set", "card", "--key", "tags")["data"] == 2
    assert run_cli(redis_endpoint, "set", "remove", "--key", "tags", "--member", "two")["data"] == 1

    assert run_cli(redis_endpoint, "zset", "add", "--key", "scores", "--mapping", '{"Ada":10,"Linus":8}')
    assert run_cli(redis_endpoint, "zset", "range", "--key", "scores", "--start", "0", "--stop", "-1")["ok"] is True
    assert run_cli(redis_endpoint, "zset", "card", "--key", "scores")["data"] == 2
    assert run_cli(redis_endpoint, "zset", "score", "--key", "scores", "--member", "Ada")["data"] == 10
    assert run_cli(redis_endpoint, "zset", "rank", "--key", "scores", "--member", "Ada")["data"] == 1
    assert run_cli(redis_endpoint, "zset", "remove", "--key", "scores", "--member", "Linus")["data"] == 1

    assert run_cli(redis_endpoint, "key", "exists", "--key", "alpha")["data"] == 1
    assert run_cli(redis_endpoint, "key", "type", "--key", "alpha")["data"] == "string"
    inspect_document = run_cli(redis_endpoint, "key", "inspect", "--key", "alpha")
    assert cast("dict[str, object]", inspect_document["data"])["type"] == "string"
    assert inspect_document["meta"] == {
        "command_group": "key",
        "action": "inspect",
        "profile": None,
        "output_mode": "json",
    }
    assert run_cli(redis_endpoint, "key", "scan", "--pattern", "*", "--limit", "100")["ok"] is True
    assert run_cli(redis_endpoint, "key", "keys", "--pattern", "*", "--page-size", "10")["ok"] is True
    assert run_cli(redis_endpoint, "key", "expire", "--key", "alpha", "--seconds", "60")["data"] == 1
    assert cast("int", run_cli(redis_endpoint, "key", "ttl", "--key", "alpha")["data"]) > 0
    assert run_cli(redis_endpoint, "key", "persist", "--key", "alpha")["data"] == 1
    assert run_cli(redis_endpoint, "key", "rename", "--key", "alpha", "--new-key", "renamed")["data"] == 1
    assert run_cli(redis_endpoint, "key", "random")["ok"] is True
    delete_document = run_cli(redis_endpoint, "key", "delete", "--key", "renamed")
    assert delete_document["data"] == 1
    assert delete_document["meta"] == {
        "command_group": "key",
        "action": "del",
        "profile": None,
        "output_mode": "json",
    }

    pipeline = json.dumps([["SET", "pipeline-key", "yes"], ["GET", "pipeline-key"]])
    pipeline_document = run_cli(redis_endpoint, "server", "pipeline", "--commands", pipeline)
    assert pipeline_document["data"] == [True, "yes"]
    assert pipeline_document["meta"] == {
        "command_group": "server",
        "action": "pipeline",
        "profile": None,
        "output_mode": "json",
    }
    assert run_cli(redis_endpoint, "server", "flushdb", "--confirm")["data"] == {"flushed": True}
