import json
from pathlib import Path

from click.testing import CliRunner

from redis_cli.cli import cli, create_runtime


def invoke_cli(tmp_path: Path, *arguments: str) -> tuple[int, dict[str, object]]:
    runner = CliRunner()
    result = runner.invoke(cli, list(arguments), obj=create_runtime(store_path=tmp_path / "connections.json"))
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
