"""SecretValue semantics that keep credentials out of rendered output."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from click.testing import CliRunner

from db_cli_kit.profiles import ProfileName
from redis_cli.application import RedisApplication
from redis_cli.cli import CliRuntime, cli
from redis_cli.domain.profiles import ConnectionOverrides, ProfileSetRequest, ProfileSettingsPatch
from redis_cli.domain.secrets import SecretValue
from redis_cli.service import ProfileService, parse_redis_url
from redis_cli.store import JsonProfileStore

from .test_application import FakeFactory, FakeRedis

if TYPE_CHECKING:
    from pathlib import Path


class MemorySecrets:
    """In-memory secret store that keeps saved profile passwords."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get(self, name: ProfileName) -> str | None:
        return self.values.get(name.value)

    def set(self, name: ProfileName, password: str) -> None:
        self.values[name.value] = password

    def delete(self, name: ProfileName) -> None:
        self.values.pop(name.value, None)


def test_secret_value_reveals_only_through_reveal() -> None:
    secret = SecretValue("hunter2")

    assert secret.reveal() == "hunter2"
    assert bool(secret) is True
    assert bool(SecretValue("")) is False


def test_secret_value_repr_and_str_do_not_expose_the_text() -> None:
    text = "hunter2"

    assert text not in repr(SecretValue(text))
    assert text not in str(SecretValue(text))


def test_secret_value_equality_compares_only_other_secret_values() -> None:
    assert SecretValue("same") == SecretValue("same")
    assert SecretValue("left") != SecretValue("right")
    assert SecretValue("text") != "text"
    assert hash(SecretValue("same")) == hash(SecretValue("same"))


def test_connection_overrides_and_parsed_url_hide_the_secret() -> None:
    secret = "s3cr3t-override-password"
    overrides = ConnectionOverrides(password=SecretValue(secret))
    parsed = parse_redis_url(f"redis://user:{secret}@example.test:6379/0")

    for rendered in (repr(overrides), str(overrides), repr(parsed), str(parsed), repr(parsed.password)):
        assert secret not in rendered
    assert parsed.password.reveal() == secret
    assert overrides.password is not None
    assert overrides.password.reveal() == secret


def test_profile_set_request_hides_the_secret() -> None:
    secret = "s3cr3t-profile-password"
    request = ProfileSetRequest(
        name=ProfileName(value="local"),
        settings=ProfileSettingsPatch(host="127.0.0.1"),
        password=SecretValue(secret),
    )

    assert secret not in repr(request)
    assert secret not in str(request)


def test_connection_status_reports_password_presence_without_the_secret(tmp_path: Path) -> None:
    secret = "s3cr3t-status-password"
    service = ProfileService(
        JsonProfileStore(tmp_path / "connections.json"),
        MemorySecrets(),
        working_directory=tmp_path,
    )
    service.set(
        ProfileSetRequest(
            name=ProfileName(value="local"),
            settings=ProfileSettingsPatch(host="127.0.0.1"),
            password=SecretValue(secret),
        )
    )
    runtime = CliRuntime(service, RedisApplication(service, FakeFactory(FakeRedis())))

    result = CliRunner().invoke(cli, ["--json", "--profile", "local", "connection", "status"], obj=runtime)

    assert result.exit_code == 0
    document = json.loads(result.output)
    assert document["data"]["password_present"] is True
    assert document["meta"]["profile"] == "local"
    assert secret not in result.output
