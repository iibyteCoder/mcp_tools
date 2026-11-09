import json
from pathlib import Path

from click.testing import CliRunner

from db_cli_kit.profiles import ProfileName
from redis_cli.application import RedisApplication
from redis_cli.cli import CliRuntime, cli, create_runtime
from redis_cli.cli_support import command_group
from redis_cli.domain.profiles import ProfileSetRequest, ProfileSettingsPatch
from redis_cli.enums import RedisCommand
from redis_cli.service import ProfileService
from redis_cli.skill_paths import resolve_dsh_home, resolve_redis_cli_skill_paths
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
    assert document == {
        "ok": True,
        "data": [],
        "meta": {
            "command_group": "profile",
            "action": "list",
            "profile": None,
            "output_mode": "json",
        },
    }


def test_connection_status_does_not_open_redis(tmp_path: Path) -> None:
    exit_code, document = invoke_cli(tmp_path, "--json", "connection", "status")

    assert exit_code == 0
    assert document["ok"] is True
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
    assert document["meta"] == {
        "command_group": "connection",
        "action": "status",
        "profile": None,
        "output_mode": "json",
    }


def test_flushdb_requires_explicit_confirmation(tmp_path: Path) -> None:
    exit_code, document = invoke_cli(tmp_path, "--json", "server", "flushdb")

    assert exit_code == 2
    assert document == {
        "ok": False,
        "error": {
            "code": "invalid_argument",
            "message": "flushdb requires --confirm",
            "retryable": False,
            "hint": None,
        },
        "meta": {
            "command_group": "server",
            "action": "flushdb",
            "profile": None,
            "output_mode": "json",
        },
    }


def test_profile_show_missing_reports_the_target_profile(tmp_path: Path) -> None:
    exit_code, document = invoke_cli(tmp_path, "--json", "profile", "show", "missing")

    assert exit_code == 4
    assert document["error"] == {
        "code": "profile_not_found",
        "message": "profile not found",
        "retryable": False,
        "hint": None,
    }
    assert document["meta"] == {
        "command_group": "profile",
        "action": "show",
        "profile": "missing",
        "output_mode": "json",
    }


def test_profile_set_rejects_the_removed_no_bind_option(tmp_path: Path) -> None:
    exit_code, document = invoke_cli(
        tmp_path,
        "--json",
        "profile",
        "set",
        "local",
        "--host",
        "127.0.0.1",
        "--no-bind",
    )

    assert exit_code == 2
    error = document["error"]
    assert isinstance(error, dict)
    assert error["code"] == "invalid_argument"
    assert "--no-bind" in str(error["message"])
    assert document["meta"] == {
        "command_group": None,
        "action": None,
        "profile": None,
        "output_mode": "json",
    }


def test_skill_path_reports_codex_and_dsh_paths(tmp_path: Path, monkeypatch) -> None:
    codex_home = tmp_path / "codex"
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    exit_code, document = invoke_cli(tmp_path, "--json", "skill", "path")

    paths = resolve_redis_cli_skill_paths()
    assert exit_code == 0
    assert document["data"] == {"codex": str(paths.codex), "dsh": str(paths.dsh)}
    assert document["data"] == {
        "codex": str(codex_home / "skills" / "redis-cli" / "SKILL.md"),
        "dsh": str(resolve_dsh_home() / "skills" / "redis-cli" / "SKILL.md"),
    }
    assert document["meta"] == {
        "command_group": "skill",
        "action": "path",
        "profile": None,
        "output_mode": "json",
    }


def test_skill_paths_use_default_codex_and_dsh_homes(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("CODEX_HOME", raising=False)

    paths = resolve_redis_cli_skill_paths(user_home=tmp_path)

    assert paths.codex == tmp_path / ".codex" / "skills" / "redis-cli" / "SKILL.md"
    assert paths.dsh == tmp_path / ".agents" / "skills" / "redis-cli" / "SKILL.md"


def test_profile_commands_cover_create_select_bind_clear_rename_validate_remove(tmp_path: Path) -> None:
    service = ProfileService(
        JsonProfileStore(tmp_path / "connections.json"),
        MemorySecrets(),
        working_directory=tmp_path,
    )
    runtime = CliRuntime(service, RedisApplication(service, FakeFactory(FakeRedis())))

    exit_code, document = invoke_with_runtime(runtime, "--json", "profile", "set", "local", "--host", "127.0.0.1")
    assert exit_code == 0
    assert document["meta"] == {
        "command_group": "profile",
        "action": "set",
        "profile": "local",
        "output_mode": "json",
    }
    assert service.current() is None
    assert invoke_with_runtime(runtime, "--json", "profile", "show", "local")[0] == 0
    assert invoke_with_runtime(runtime, "--json", "profile", "select", "local")[0] == 0
    assert invoke_with_runtime(runtime, "--json", "profile", "current")[1]["data"] != {"profile": None}
    assert (
        invoke_with_runtime(runtime, "--json", "profile", "bind", "local", "--path", str(tmp_path / "nested"))[0] == 0
    )
    exit_code, document = invoke_with_runtime(runtime, "--json", "use", "local", "--path", str(tmp_path))
    assert exit_code == 0
    assert document["meta"]["action"] == "use"
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


def test_data_commands_report_family_and_redis_command_name(tmp_path: Path) -> None:
    service = ProfileService(
        JsonProfileStore(tmp_path / "connections.json"),
        MemorySecrets(),
        working_directory=tmp_path,
    )
    service.set(
        ProfileSetRequest(
            name=ProfileName(value="local"),
            settings=ProfileSettingsPatch(host="127.0.0.1"),
        )
    )
    runtime = CliRuntime(service, RedisApplication(service, FakeFactory(FakeRedis())))

    exit_code, document = invoke_with_runtime(
        runtime,
        "--profile",
        "local",
        "--json",
        "string",
        "set",
        "--key",
        "alpha",
        "--value",
        "one",
    )

    assert exit_code == 0
    assert document["meta"] == {
        "command_group": "string",
        "action": "set",
        "profile": "local",
        "output_mode": "json",
    }
    exit_code, document = invoke_with_runtime(
        runtime, "--profile", "local", "--json", "key", "delete", "--key", "alpha"
    )
    assert exit_code == 0
    assert document["meta"] == {
        "command_group": "key",
        "action": "del",
        "profile": "local",
        "output_mode": "json",
    }


def test_every_redis_command_belongs_to_a_command_group() -> None:
    for command in RedisCommand:
        assert command_group(command) is not None
