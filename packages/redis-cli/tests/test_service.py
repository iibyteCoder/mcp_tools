from pathlib import Path

from redis_cli.domain import (
    ConnectionOverrides,
    ProfileName,
    ProfileSetRequest,
    ProfileSettingsPatch,
)
from redis_cli.enums import ProfileSelectionSource
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
    assert parsed.password == "p@ss"
    assert parsed.tls is True


def test_profile_round_trip_resolves_directory_binding(tmp_path: Path) -> None:
    service, secrets = create_service(tmp_path)
    name = ProfileName("local")

    record = service.set(
        ProfileSetRequest(
            name=name,
            settings=ProfileSettingsPatch(host="127.0.0.1", port=6379),
            password="secret",
        )
    )

    resolved = service.resolve(None, ConnectionOverrides())

    assert record.password_present is True
    assert secrets.values == {"local": "secret"}
    assert resolved.profile == name
    assert resolved.source is ProfileSelectionSource.DIRECTORY
    assert resolved.config.password == "secret"
