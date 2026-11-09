from pathlib import Path
from typing import cast

from db_cli_kit.profiles import ProfileName
from redis_cli.application import RedisApplication
from redis_cli.domain.profiles import (
    ConnectionOverrides,
    ProfileSetRequest,
    ProfileSettingsPatch,
    RedisConnectionConfig,
)
from redis_cli.ports.redis_client import RedisClient
from redis_cli.service import ProfileService
from redis_cli.store import JsonProfileStore


class MemorySecrets:
    def get(self, name: ProfileName) -> str | None:
        return None

    def set(self, name: ProfileName, password: str) -> None:
        return None

    def delete(self, name: ProfileName) -> None:
        return None


class FakeRedis:
    def ping(self) -> bool:
        return True

    def execute_command(self, command: str, *arguments: object) -> object:
        return "OK"

    def close(self) -> None:
        return None


class FakeFactory:
    def __init__(self, client: FakeRedis) -> None:
        self.client = client

    def create(self, config: RedisConnectionConfig) -> RedisClient:
        return cast("RedisClient", self.client)


def test_ping_uses_client_boundary_and_closes_client(tmp_path: Path) -> None:
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
    application = RedisApplication(service, FakeFactory(FakeRedis()))

    result = application.ping(ProfileName(value="local"), ConnectionOverrides())

    assert result.profile == ProfileName(value="local")
    assert result.data == {"pong": True}
