import json
from pathlib import Path

from click.testing import CliRunner

from redis_cli.application import RedisApplication
from redis_cli.cli import CliRuntime, cli, create_runtime
from redis_cli.service import ProfileService
from redis_cli.store import JsonProfileStore

from .test_application import FakeFactory, FakeRedis, MemorySecrets


def invoke_cli(tmp_path: Path, *arguments: str) -> tuple[int, dict[str, object]]:
    runner = CliRunner()
    result = runner.invoke(cli, list(arguments), obj=create_runtime(store_path=tmp_path / "connections.json"))
    document = json.loads(result.output)
    return result.exit_code, document


def invoke_with_runtime(runtime: CliRuntime, *arguments: str) -> tuple[int, dict[str, object]]:
    runner = CliRunner()
    result = runner.invoke(cli, list(arguments), obj=runtime)
    document = json.loads(result.output)
    return result.exit_code, document


def test_profile_list_emits_stable_json_envelope(tmp_path: Path) -> None:
    exit_code, document = invoke_cli(tmp_path, "--json", "profile", "list")

    assert exit_code == 0
    assert document == {"status": "success", "profile": None, "data": []}


def test_connection_status_does_not_open_redis(tmp_path: Path) -> None:
    exit_code, document = invoke_cli(tmp_path, "--json", "connection", "status")

    assert exit_code == 0
    assert document["status"] == "success"
    assert document["data"] == {
        "source": "defaults",
        "host": "localhost",
        "port": 6379,
        "username": "",
        "database": 0,
        "connection_timeout": 5.0,
        "tls": False,
        "password_present": False,
    }


def test_flushdb_requires_explicit_confirmation(tmp_path: Path) -> None:
    exit_code, document = invoke_cli(tmp_path, "--json", "server", "flushdb")

    assert exit_code == 2
    assert document["error"] == {
        "code": "INVALID_ARGUMENT",
        "message": "flushdb requires --confirm",
    }


def test_profile_commands_cover_create_select_bind_clear_rename_validate_remove(tmp_path: Path) -> None:
    service = ProfileService(
        JsonProfileStore(tmp_path / "connections.json"),
        MemorySecrets(),
        working_directory=tmp_path,
    )
    runtime = CliRuntime(service, RedisApplication(service, FakeFactory(FakeRedis())))

    assert invoke_with_runtime(runtime, "--json", "profile", "set", "local", "--host", "127.0.0.1", "--no-bind")[0] == 0
    assert invoke_with_runtime(runtime, "--json", "profile", "show", "local")[0] == 0
    assert invoke_with_runtime(runtime, "--json", "profile", "select", "local")[0] == 0
    assert invoke_with_runtime(runtime, "--json", "profile", "current")[1]["data"] != {"profile": None}
    assert (
        invoke_with_runtime(runtime, "--json", "profile", "bind", "local", "--path", str(tmp_path / "nested"))[0] == 0
    )
    assert invoke_with_runtime(runtime, "--json", "use", "local", "--path", str(tmp_path))[0] == 0
    assert invoke_with_runtime(runtime, "--json", "profile", "clear", "--path", str(tmp_path))[0] == 0
    assert invoke_with_runtime(runtime, "--json", "profile", "rename", "local", "renamed")[0] == 0
    assert invoke_with_runtime(runtime, "--json", "profile", "validate", "renamed")[1]["data"] == {
        "validated": True,
        "pong": True,
    }
    assert invoke_with_runtime(runtime, "--json", "profile", "remove", "renamed")[1]["data"] == {
        "removed": True,
        "bindings_removed": 1,
    }
    assert invoke_with_runtime(runtime, "--json", "profile", "list")[1]["data"] == []
