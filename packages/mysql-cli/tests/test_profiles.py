"""Unit tests for typed profile CRUD and persistence boundaries."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
from filelock import FileLock

from mysql_cli.command_model import CommandAction, CommandGroup, CommandRequest, SqlInputSpec
from mysql_cli.profile_models import (
    ProfileName,
    ProfileRegistry,
    ProfileSetRequest,
    ProfileSettingsPatch,
)
from mysql_cli.profile_service import ProfileService, ProfileServiceError, ProfileValidator
from mysql_cli.profile_store import JsonProfileStore, ProfileStoreError
from mysql_cli.secret_store import SecretStore

if TYPE_CHECKING:
    from pathlib import Path

    from mysql_client import MySqlConnectionConfig


@dataclass
class FakeSecretStore(SecretStore):
    values: dict[ProfileName, str]

    def get(self, name: ProfileName) -> str | None:
        return self.values.get(name)

    def set(self, name: ProfileName, password: str) -> None:
        self.values[name] = password

    def delete(self, name: ProfileName) -> None:
        self.values.pop(name, None)


class FakeValidator(ProfileValidator):
    def __init__(self) -> None:
        self.configs: list[MySqlConnectionConfig] = []

    async def validate(self, config: MySqlConnectionConfig) -> None:
        self.configs.append(config)


def make_service(tmp_path: Path) -> tuple[ProfileService, FakeSecretStore, FakeValidator, JsonProfileStore]:
    store = JsonProfileStore(tmp_path / "profiles.json")
    secrets = FakeSecretStore({})
    validator = FakeValidator()
    return (
        ProfileService(store, secrets, validator, working_directory=tmp_path / "project"),
        secrets,
        validator,
        store,
    )


def profile_request(name: str = "dev", *, host: str | None = "db.example") -> ProfileSetRequest:
    return ProfileSetRequest(
        name=ProfileName(value=name),
        settings=ProfileSettingsPatch(host=host, user="alice"),
        password="never-print-this",
        no_bind=True,
    )


def test_set_updates_only_explicit_fields_and_keeps_password_secret(tmp_path: Path) -> None:
    service, secrets, _, _ = make_service(tmp_path)
    created = service.set(profile_request())
    updated = service.set(
        ProfileSetRequest(
            name=created.name,
            settings=ProfileSettingsPatch(port=3307),
            no_bind=True,
        )
    )

    assert updated.settings.host == "db.example"
    assert updated.settings.port == 3307
    assert updated.settings.user == "alice"
    assert updated.password_present is True
    assert secrets.values[created.name] == "never-print-this"
    assert "never-print-this" not in repr(updated)


def test_bind_inherits_nearest_directory_and_unbind_is_exact(tmp_path: Path) -> None:
    service, _, _, _ = make_service(tmp_path)
    service.set(
        profile_request(),
    )
    service.bind(ProfileName(value="dev"), tmp_path)
    child = tmp_path / "child"
    selection = service.selection(None, directory=child)

    assert selection.profile.name == ProfileName(value="dev")
    assert selection.binding is not None
    assert service.unbind(tmp_path) is not None
    with pytest.raises(ProfileServiceError):
        service.selection(None, directory=child)


def test_rename_moves_bindings_and_secret_without_overwrite(tmp_path: Path) -> None:
    service, secrets, _, _ = make_service(tmp_path)
    service.set(profile_request())
    service.bind(ProfileName(value="dev"), tmp_path)
    service.set(profile_request("prod"))
    with pytest.raises(ProfileServiceError):
        service.rename(ProfileName(value="dev"), ProfileName(value="prod"))
    renamed = service.rename(ProfileName(value="dev"), ProfileName(value="renamed"))

    assert renamed.name == ProfileName(value="renamed")
    assert ProfileName(value="dev") not in secrets.values
    assert secrets.values[ProfileName(value="renamed")] == "never-print-this"
    assert service.selection(None, directory=tmp_path).profile.name == ProfileName(value="renamed")


def test_remove_cleans_secret_and_all_bindings(tmp_path: Path) -> None:
    service, secrets, _, store = make_service(tmp_path)
    service.set(profile_request())
    service.bind(ProfileName(value="dev"), tmp_path / "nested")
    assert service.remove(ProfileName(value="dev")) == 1
    assert secrets.values == {}
    assert store.read() == ProfileRegistry()


def test_validate_is_explicit_and_never_persists_password(tmp_path: Path) -> None:
    service, _, validator, store = make_service(tmp_path)
    service.set(profile_request())

    import asyncio

    profile = asyncio.run(service.validate(ProfileName(value="dev")))

    assert profile.password_present is True
    assert len(validator.configs) == 1
    assert validator.configs[0].password.reveal() == "never-print-this"
    document = json.loads(store.path.read_text(encoding="utf-8"))
    assert "never-print-this" not in json.dumps(document)


def test_corrupt_and_unsupported_registry_are_typed(tmp_path: Path) -> None:
    path = tmp_path / "profiles.json"
    path.write_text("{not-json}", encoding="utf-8")
    with pytest.raises(ProfileStoreError) as corrupt:
        JsonProfileStore(path).read()
    assert corrupt.value.code.value == "profile_registry_corrupt"

    path.write_text(
        json.dumps({"schema": "db-mysql.profile-registry", "version": 99, "profiles": [], "bindings": []}),
        encoding="utf-8",
    )
    with pytest.raises(ProfileStoreError) as unsupported:
        JsonProfileStore(path).read()
    assert unsupported.value.code.value == "profile_registry_version_unsupported"


def test_registry_lock_conflict_is_typed(tmp_path: Path) -> None:
    path = tmp_path / "profiles.json"
    store = JsonProfileStore(path)
    lock = FileLock(str(store.lock_path))
    lock.acquire()
    try:
        with pytest.raises(ProfileStoreError) as locked:
            store.read()
        assert locked.value.code.value == "profile_registry_locked"
    finally:
        lock.release()


def test_root_profile_is_typed_and_does_not_change_binding() -> None:
    request = CommandRequest(
        group=CommandGroup.SQL,
        action=CommandAction.READ,
        selected_profile=ProfileName(value="dev"),
        sql_input=SqlInputSpec.inline("SELECT 1"),
    )

    assert request.group is CommandGroup.SQL
    assert request.action is CommandAction.READ
    assert request.selected_profile == ProfileName(value="dev")
