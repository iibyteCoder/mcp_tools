from pathlib import Path

import pytest

from db_cli_kit.profiles import ProfileName
from redis_cli.domain.errors import RedisCliError
from redis_cli.domain.profiles import (
    ConnectionOverrides,
    ProfileSetRequest,
    ProfileSettingsPatch,
)
from redis_cli.domain.secrets import SecretValue
from redis_cli.enums import ErrorCode, ProfileSelectionSource
from redis_cli.service import ProfileService, parse_redis_url
from redis_cli.store import JsonProfileStore


class MemorySecrets:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get(self, name: ProfileName) -> str | None:
        return self.values.get(name.value)

    def set(self, name: ProfileName, password: str) -> None:
        self.values[name.value] = password

    def delete(self, name: ProfileName) -> None:
        self.values.pop(name.value, None)


def create_service(tmp_path: Path) -> tuple[ProfileService, MemorySecrets]:
    secrets = MemorySecrets()
    service = ProfileService(
        JsonProfileStore(tmp_path / "connections.json"),
        secrets,
        working_directory=tmp_path,
    )
    return service, secrets


def test_parse_redis_url_returns_strict_connection_parts() -> None:
    parsed = parse_redis_url("rediss://user:p%40ss@example.test:6380/4")

    assert parsed.settings.host == "example.test"
    assert parsed.settings.port == 6380
    assert parsed.settings.username == "user"
    assert parsed.settings.database == 4
    assert parsed.password.reveal() == "p@ss"
    assert parsed.tls is True


def test_profile_round_trip_resolves_explicit_directory_binding(tmp_path: Path) -> None:
    service, secrets = create_service(tmp_path)
    name = ProfileName(value="local")

    record = service.set(
        ProfileSetRequest(
            name=name,
            settings=ProfileSettingsPatch(host="127.0.0.1", port=6379),
            password=SecretValue("secret"),
        )
    )
    service.bind(name)

    resolved = service.resolve(None, ConnectionOverrides())

    assert record.password_present is True
    assert secrets.values == {"local": "secret"}
    assert resolved.profile == name
    assert resolved.source is ProfileSelectionSource.DIRECTORY
    assert resolved.config.password.reveal() == "secret"


def test_profile_set_does_not_create_a_directory_binding(tmp_path: Path) -> None:
    service, _ = create_service(tmp_path)

    service.set(
        ProfileSetRequest(
            name=ProfileName(value="local"),
            settings=ProfileSettingsPatch(host="127.0.0.1"),
        )
    )

    assert service.current() is None
    assert service.store.read().bindings == ()
    assert service.resolve(None, ConnectionOverrides()).source is ProfileSelectionSource.DEFAULTS


def test_profile_set_preserves_existing_directory_bindings(tmp_path: Path) -> None:
    service, _ = create_service(tmp_path)
    name = ProfileName(value="local")
    service.set(ProfileSetRequest(name=name, settings=ProfileSettingsPatch(host="127.0.0.1")))
    service.bind(name)

    service.set(ProfileSetRequest(name=name, settings=ProfileSettingsPatch(port=6380)))

    selection = service.current()
    assert selection is not None
    assert selection.binding is not None
    assert service.store.read().bindings[0].profile == name


def test_profile_set_rejects_an_empty_password(tmp_path: Path) -> None:
    service, _ = create_service(tmp_path)

    with pytest.raises(RedisCliError) as failure:
        service.set(
            ProfileSetRequest(
                name=ProfileName(value="local"),
                settings=ProfileSettingsPatch(host="127.0.0.1"),
                password=SecretValue(""),
            )
        )

    assert failure.value.code is ErrorCode.INVALID_ARGUMENT
