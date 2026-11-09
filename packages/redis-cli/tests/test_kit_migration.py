"""Architecture and compatibility contracts for the db-cli-kit migration."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import cast

import pytest
from click.testing import CliRunner
from platformdirs import user_config_path

from db_cli_kit.json_codec import JsonValue as KitJsonValue
from db_cli_kit.profiles import normalize_directory
from db_cli_kit.secrets import KeyringSecretStore
from redis_cli import domain, json_types, rendering, service, store
from redis_cli.cli import cli, create_runtime
from redis_cli.constants import (
    PASSWORD_SERVICE_NAME,
    PROFILE_REGISTRY_DIRECTORY,
    PROFILE_REGISTRY_FILE_NAME,
)
from redis_cli.domain import errors
from redis_cli.domain.errors import RedisCliError
from redis_cli.enums import ErrorCode, RegistrySchema
from redis_cli.store import JsonProfileStore


def _existing_registry_document(directory: Path) -> dict[str, object]:
    return {
        "schema": "db-cli.redis-connections",
        "version": 1,
        "profiles": [
            {
                "name": "local",
                "settings": {
                    "host": "127.0.0.1",
                    "port": 6379,
                    "username": "",
                    "database": 0,
                    "connection_timeout": 5.0,
                    "tls": False,
                },
                "description": "existing profile",
                "password_present": False,
            }
        ],
        "bindings": [{"path": str(normalize_directory(directory)), "profile": "local"}],
    }


def test_default_profile_path_schema_and_version_are_unchanged() -> None:
    store = JsonProfileStore()

    assert store.path == user_config_path(PROFILE_REGISTRY_DIRECTORY) / PROFILE_REGISTRY_FILE_NAME
    assert store.path.name == "connections.json"
    assert store.path.parent.name == "db-cli"
    assert store.lock_path == Path(f"{store.path}.lock")
    assert RegistrySchema.REDIS_CONNECTIONS.value == JsonProfileStore.SCHEMA
    assert JsonProfileStore.SCHEMA == "db-cli.redis-connections"
    assert JsonProfileStore.VERSION == 1
    assert JsonProfileStore.LOCK_TIMEOUT_SECONDS == 1.0


def test_existing_registry_document_is_read_and_written_unchanged(tmp_path: Path) -> None:
    path = tmp_path / "connections.json"
    directory = tmp_path / "workspace"
    document = _existing_registry_document(directory)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    store = JsonProfileStore(path)

    registry = store.read()

    assert [record.name.value for record in registry.profiles] == ["local"]
    assert registry.profiles[0].settings.host == "127.0.0.1"
    assert registry.profiles[0].settings.port == 6379
    assert registry.bindings[0].path == normalize_directory(directory)
    store.update(lambda current: current)

    rewritten = cast("dict[str, object]", json.loads(path.read_text(encoding="utf-8")))
    assert rewritten == document
    profiles = cast("list[dict[str, object]]", rewritten["profiles"])
    settings = cast("dict[str, object]", profiles[0]["settings"])
    bindings = cast("list[dict[str, object]]", rewritten["bindings"])
    assert set(rewritten) == {"schema", "version", "profiles", "bindings"}
    assert set(profiles[0]) == {"name", "settings", "description", "password_present"}
    assert set(settings) == {"host", "port", "username", "database", "connection_timeout", "tls"}
    assert set(bindings[0]) == {"path", "profile"}


def test_profile_store_errors_use_the_single_cli_error_code(tmp_path: Path) -> None:
    path = tmp_path / "connections.json"
    path.write_text("{not-json}", encoding="utf-8")

    with pytest.raises(RedisCliError, match="profile registry is unreadable or invalid") as unreadable:
        JsonProfileStore(path).read()
    assert unreadable.value.code is ErrorCode.PROFILE_REGISTRY
    assert unreadable.value.retryable is False

    path.write_text(
        json.dumps({"schema": "unsupported", "version": 1, "profiles": [], "bindings": []}),
        encoding="utf-8",
    )
    with pytest.raises(RedisCliError, match="profile registry schema is unsupported") as unsupported:
        JsonProfileStore(path).read()
    assert unsupported.value.code is ErrorCode.PROFILE_REGISTRY


def test_runtime_uses_the_db_redis_keyring_service(tmp_path: Path) -> None:
    runtime = create_runtime(store_path=tmp_path / "connections.json")

    secret_store = runtime.profile_service.secret_store

    assert isinstance(secret_store, KeyringSecretStore)
    assert secret_store.service == "db-redis"
    assert secret_store.service == PASSWORD_SERVICE_NAME


def test_success_envelope_is_compact_json_with_one_newline(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        cli,
        ["--json", "profile", "list"],
        obj=create_runtime(store_path=tmp_path / "connections.json"),
    )

    assert result.exit_code == 0
    assert result.output.replace("\r\n", "\n") == (
        '{"ok":true,"data":[],"meta":{"command_group":"profile","action":"list","profile":null,"output_mode":"json"}}\n'
    )


def test_error_envelope_is_compact_json_with_one_newline(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        cli,
        ["--json", "server", "flushdb"],
        obj=create_runtime(store_path=tmp_path / "connections.json"),
    )

    assert result.exit_code == 2
    assert result.output.replace("\r\n", "\n") == (
        '{"ok":false,"error":{"code":"invalid_argument","message":"flushdb requires --confirm",'
        '"retryable":false,"hint":null},'
        '"meta":{"command_group":"server","action":"flushdb","profile":null,"output_mode":"json"}}\n'
    )


def test_legacy_exception_classes_are_removed() -> None:
    assert not hasattr(errors, "RedisOperationError")
    assert not hasattr(service, "ProfileServiceError")
    assert not hasattr(store, "ProfileStoreError")
    assert not hasattr(rendering, "CliError")


def test_json_value_and_output_are_kit_aliases_at_runtime() -> None:
    assert json_types.JsonValue is KitJsonValue
    assert json_types.JsonOutput is KitJsonValue
    assert json_types.JsonValue is not object
    assert json_types.JsonOutput is not object


def test_domain_does_not_reexport_kit_profile_primitives() -> None:
    assert not hasattr(domain, "__all__")
    for name in ("ProfileName", "DirectoryBinding", "ProfileNameError", "normalize_directory"):
        assert not hasattr(domain, name)


def test_secrets_module_is_removed() -> None:
    assert importlib.util.find_spec("redis_cli.secrets") is None

    source_root = Path(__file__).resolve().parents[1] / "src" / "redis_cli"
    references = [
        source_file
        for source_file in source_root.rglob("*.py")
        if "redis_cli.secrets" in source_file.read_text(encoding="utf-8")
    ]
    assert references == []
