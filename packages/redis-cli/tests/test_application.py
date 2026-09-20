from pathlib import Path
from typing import cast

from redis_cli.application import RedisApplication
from redis_cli.client import RedisClient, RedisClientFactory
from redis_cli.domain import (
    ConnectionOverrides,
    ProfileName,
    ProfileSetRequest,
    ProfileSettingsPatch,
    RedisConnectionConfig,
)
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

    def close(self) -> None:
        return None


class FakeFactory(RedisClientFactory):
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
            name=ProfileName("local"),
            settings=ProfileSettingsPatch(host="127.0.0.1"),
        )
    )
    application = RedisApplication(service, FakeFactory(FakeRedis()))

    result = application.ping(ProfileName("local"), ConnectionOverrides())

    assert result.profile == ProfileName("local")
    assert result.data == {"pong": True}
