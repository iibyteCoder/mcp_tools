"""Tests for the concrete aiomysql driver adapter."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from mysql_client import AiomysqlDriverFactory, MySqlConnectionConfig, SecretValue

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch


class FakeAiomysqlModule:
    """A 0.3.2-shaped module whose connect API has no read_timeout option."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def connect(
        self,
        *,
        host: str,
        port: int,
        user: str,
        password: str,
        db: str | None,
        charset: str,
        connect_timeout: float,
        autocommit: bool,
    ) -> object:
        self.calls.append(
            {
                "host": host,
                "port": port,
                "user": user,
                "password": password,
                "db": db,
                "charset": charset,
                "connect_timeout": connect_timeout,
                "autocommit": autocommit,
            }
        )
        return object()


def test_connect_uses_only_aiomysql_supported_options(monkeypatch: MonkeyPatch) -> None:
    fake_module = FakeAiomysqlModule()

    def import_module(name: str) -> FakeAiomysqlModule:
        assert name == "aiomysql"
        return fake_module

    monkeypatch.setattr("mysql_client.adapters.aiomysql.importlib.import_module", import_module)
    config = MySqlConnectionConfig(
        host="db.example",
        port=3316,
        user="alice",
        password=SecretValue(_value="secret"),
        database="aica_test",
        connect_timeout_seconds=10.0,
        read_timeout_seconds=600.0,
    )

    asyncio.run(AiomysqlDriverFactory().connect(config))

    assert fake_module.calls == [
        {
            "host": "db.example",
            "port": 3316,
            "user": "alice",
            "password": "secret",
            "db": "aica_test",
            "charset": "utf8mb4",
            "connect_timeout": 10.0,
            "autocommit": False,
        }
    ]
