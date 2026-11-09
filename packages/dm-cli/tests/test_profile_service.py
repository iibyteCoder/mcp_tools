"""Unit tests for the DM profile application service."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest

from db_cli_kit.profiles import ProfileName
from dm_cli.adapters.profile_store import JsonProfileStore
from dm_cli.application.profile import (
    ProfileService,
    ProfileServiceError,
    ProfileServiceErrorCode,
    ProfileValidator,
)
from dm_cli.domain.profile import ProfileRegistry, ProfileSetRequest, ProfileSettingsPatch
from dm_cli.ports.secret_store import SecretStore

if TYPE_CHECKING:
    from pathlib import Path

    from dm_client.domain.configuration import DmConnectionConfig


@dataclass
class FakeSecretStore(SecretStore):
    values: dict[ProfileName, str] = field(default_factory=dict)

    def get(self, name: ProfileName) -> str | None:
        return self.values.get(name)

    def set(self, name: ProfileName, password: str) -> None:
        self.values[name] = password

    def delete(self, name: ProfileName) -> None:
        self.values.pop(name, None)


class FakeValidator(ProfileValidator):
    def __init__(self) -> None:
        self.configs: list[DmConnectionConfig] = []

    async def validate(self, config: DmConnectionConfig) -> None:
        self.configs.append(config)


def make_service(
    tmp_path: Path,
    *,
    validator: ProfileValidator | None = None,
) -> tuple[ProfileService, FakeSecretStore, JsonProfileStore]:
    store = JsonProfileStore(tmp_path / "profiles.json", lock_timeout=0.0)
    secrets = FakeSecretStore()
    return ProfileService(store, secrets, validator, working_directory=tmp_path / "project"), secrets, store


def profile_request(name: str = "dev", *, host: str | None = "db.example") -> ProfileSetRequest:
    return ProfileSetRequest(
        name=ProfileName(value=name),
        settings=ProfileSettingsPatch(host=host, user="SYSDBA", schema="APP"),
        password="never-print-this",
    )


def test_set_creates_defaults_and_keeps_password_secret(tmp_path: Path) -> None:
    service, secrets, _ = make_service(tmp_path)

    created = service.set(profile_request())

    assert created.settings.port == 5236
    assert created.settings.connect_timeout == 5.0
    assert created.settings.query_timeout == 0.0
    assert created.settings.schema == "APP"
    assert created.password_present is True
    assert secrets.values[ProfileName(value="dev")] == "never-print-this"
    assert "never-print-this" not in repr(created)


def test_set_updates_only_supplied_fields_and_clears_schema(tmp_path: Path) -> None:
    service, _, _ = make_service(tmp_path)
    service.set(profile_request())

    updated = service.set(
        ProfileSetRequest(
            name=ProfileName(value="dev"),
            settings=ProfileSettingsPatch(port=5237),
        )
    )
    cleared = service.set(
        ProfileSetRequest(
            name=ProfileName(value="dev"),
            settings=ProfileSettingsPatch(clear_schema=True),
        )
    )

    assert updated.settings.host == "db.example"
    assert updated.settings.user == "SYSDBA"
    assert updated.settings.port == 5237
    assert updated.settings.schema == "APP"
    assert cleared.settings.schema is None
    assert cleared.password_present is True


def test_new_profile_requires_host_and_user(tmp_path: Path) -> None:
    service, _, _ = make_service(tmp_path)

    with pytest.raises(ProfileServiceError) as failure:
        service.set(ProfileSetRequest(name=ProfileName(value="dev"), settings=ProfileSettingsPatch(user="SYSDBA")))

    assert failure.value.code is ProfileServiceErrorCode.INVALID


def test_invalid_setting_is_reported_as_profile_invalid(tmp_path: Path) -> None:
    service, _, _ = make_service(tmp_path)

    with pytest.raises(ProfileServiceError) as failure:
        service.set(
            ProfileSetRequest(
                name=ProfileName(value="dev"),
                settings=ProfileSettingsPatch(host="db.example", user="SYSDBA", connect_timeout=0.0),
            )
        )

    assert failure.value.code is ProfileServiceErrorCode.INVALID


def test_description_is_updated_and_cleared(tmp_path: Path) -> None:
    service, _, _ = make_service(tmp_path)
    service.set(profile_request())

    described = service.set(
        ProfileSetRequest(
            name=ProfileName(value="dev"),
            settings=ProfileSettingsPatch(),
            description="read-mostly",
        )
    )
    cleared = service.set(
        ProfileSetRequest(
            name=ProfileName(value="dev"),
            settings=ProfileSettingsPatch(),
            clear_description=True,
        )
    )

    assert described.description == "read-mostly"
    assert cleared.description is None


def test_bind_inherits_nearest_directory_and_unbind_is_exact(tmp_path: Path) -> None:
    service, _, _ = make_service(tmp_path)
    service.set(profile_request())

    binding = service.bind(ProfileName(value="dev"), tmp_path)
    child = tmp_path / "child"
    selection = service.selection(None, directory=child)

    assert binding.path == tmp_path.resolve()
    assert selection.profile.name == ProfileName(value="dev")
    assert service.unbind(tmp_path) is not None
    with pytest.raises(ProfileServiceError):
        service.selection(None, directory=child)


def test_selection_prefers_explicit_profile(tmp_path: Path) -> None:
    service, _, _ = make_service(tmp_path)
    service.set(profile_request())
    service.set(profile_request("prod"))

    selection = service.selection(ProfileName(value="prod"), directory=tmp_path)

    assert selection.profile.name == ProfileName(value="prod")


def test_rename_moves_bindings_and_secret_without_overwrite(tmp_path: Path) -> None:
    service, secrets, _ = make_service(tmp_path)
    service.set(profile_request())
    service.bind(ProfileName(value="dev"), tmp_path)
    service.set(profile_request("prod"))

    with pytest.raises(ProfileServiceError) as conflict:
        service.rename(ProfileName(value="dev"), ProfileName(value="prod"))
    renamed = service.rename(ProfileName(value="dev"), ProfileName(value="renamed"))

    assert conflict.value.code is ProfileServiceErrorCode.CONFLICT
    assert renamed.name == ProfileName(value="renamed")
    assert ProfileName(value="dev") not in secrets.values
    assert secrets.values[ProfileName(value="renamed")] == "never-print-this"
    assert service.selection(None, directory=tmp_path).profile.name == ProfileName(value="renamed")


def test_remove_cleans_secret_and_all_bindings(tmp_path: Path) -> None:
    service, secrets, store = make_service(tmp_path)
    service.set(profile_request())
    service.bind(ProfileName(value="dev"), tmp_path / "nested")

    assert service.remove(ProfileName(value="dev")) == 1
    assert secrets.values == {}
    assert store.read() == ProfileRegistry()


def test_connection_config_maps_profile_and_secret(tmp_path: Path) -> None:
    service, _, _ = make_service(tmp_path)
    profile = service.set(profile_request())

    config = service.connection_config(profile)

    assert config.host == "db.example"
    assert config.port == 5236
    assert config.user == "SYSDBA"
    assert config.schema is not None
    assert config.schema.value == "APP"
    assert config.password.reveal() == "never-print-this"


def test_connection_config_requires_a_present_secret(tmp_path: Path) -> None:
    service, _, _ = make_service(tmp_path)
    profile = service.set(
        ProfileSetRequest(
            name=ProfileName(value="dev"),
            settings=ProfileSettingsPatch(host="db.example", user="SYSDBA"),
            clear_password=True,
        )
    )

    with pytest.raises(ProfileServiceError) as failure:
        service.connection_config(profile)

    assert failure.value.code is ProfileServiceErrorCode.SECRET_MISSING


def test_validate_without_validator_is_typed(tmp_path: Path) -> None:
    service, _, _ = make_service(tmp_path)
    service.set(profile_request())

    with pytest.raises(ProfileServiceError) as failure:
        asyncio.run(service.validate(ProfileName(value="dev")))

    assert failure.value.code is ProfileServiceErrorCode.VALIDATION_FAILED
    assert failure.value.message == "profile validator is not configured"


def test_validate_delegates_to_the_configured_validator(tmp_path: Path) -> None:
    validator = FakeValidator()
    service, _, _ = make_service(tmp_path, validator=validator)
    service.set(profile_request())

    profile = asyncio.run(service.validate(ProfileName(value="dev")))

    assert profile.password_present is True
    assert len(validator.configs) == 1
    assert validator.configs[0].password.reveal() == "never-print-this"
