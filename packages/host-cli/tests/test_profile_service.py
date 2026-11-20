"""Profile lifecycle: list, show, set, rename, remove, and credentials.

Credentials are exercised against an in-memory store rather than the OS keyring,
so these tests never read or write the real credential store. The store double is
the same protocol the production code consumes, so the behaviour under test is
the behaviour that ships.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from db_cli_kit.profiles import ProfileName
from db_cli_kit.secrets import SecretStoreError
from host_cli.application.profile_service import ProfileService
from host_cli.domain.enums import ErrorCode
from host_cli.domain.errors import HostCliError
from host_cli.domain.models import ProfileSettings
from host_cli.infrastructure.credentials import PasswordStore
from host_cli.infrastructure.profile_store import ProfileStore

if TYPE_CHECKING:
    from pathlib import Path

NAME = ProfileName(value="dev")
OTHER = ProfileName(value="prod")
HOST = "example"
USER = "operator"


class MemorySecretStore:
    """In-memory stand-in for the OS credential store."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.unavailable = False

    def get(self, name: ProfileName) -> str | None:
        if self.unavailable:
            raise SecretStoreError("unavailable")
        return self.values.get(name.value)

    def set(self, name: ProfileName, password: str) -> None:
        if self.unavailable:
            raise SecretStoreError("unavailable")
        self.values[name.value] = password

    def delete(self, name: ProfileName) -> None:
        if self.unavailable:
            raise SecretStoreError("unavailable")
        self.values.pop(name.value, None)


@pytest.fixture
def secrets() -> MemorySecretStore:
    return MemorySecretStore()


@pytest.fixture
def service(tmp_path: Path, secrets: MemorySecretStore) -> ProfileService:
    return ProfileService(ProfileStore(tmp_path / "profiles.json"), PasswordStore(secrets))


def add(service: ProfileService, name: ProfileName = NAME, **overrides: object) -> None:
    """Create one profile with sensible defaults."""

    settings: dict[str, object] = {"host": HOST, "user": USER}
    settings.update(overrides)
    service.set(
        name,
        host=settings.get("host"),  # type: ignore[arg-type]
        user=settings.get("user"),  # type: ignore[arg-type]
        port=settings.get("port"),  # type: ignore[arg-type]
        description=settings.get("description"),  # type: ignore[arg-type]
        clear_description=False,
        command_timeout=settings.get("command_timeout"),  # type: ignore[arg-type]
    )


def test_set_creates_a_profile(service: ProfileService) -> None:
    add(service)

    view = service.get(NAME)
    assert view.settings.host == HOST
    assert view.settings.user == USER
    assert view.settings.port == 22
    assert view.password_present is False


def test_set_requires_host_and_user_for_a_new_profile(service: ProfileService) -> None:
    with pytest.raises(HostCliError) as raised:
        service.set(
            NAME,
            host=None,
            user=None,
            port=None,
            description=None,
            clear_description=False,
            command_timeout=None,
        )

    assert raised.value.code is ErrorCode.INVALID_ARGUMENT


def test_set_updates_only_the_fields_given(service: ProfileService) -> None:
    add(service, description="first note")

    service.set(
        NAME,
        host=None,
        user=None,
        port=2222,
        description=None,
        clear_description=False,
        command_timeout=None,
    )

    view = service.get(NAME)
    assert view.settings.port == 2222
    assert view.settings.host == HOST
    assert view.settings.description == "first note"


def test_set_can_clear_a_description(service: ProfileService) -> None:
    add(service, description="note")

    service.set(
        NAME,
        host=None,
        user=None,
        port=None,
        description=None,
        clear_description=True,
        command_timeout=None,
    )

    assert service.get(NAME).settings.description is None


def test_set_rejects_conflicting_description_options(service: ProfileService) -> None:
    with pytest.raises(HostCliError):
        service.set(
            NAME,
            host=HOST,
            user=USER,
            port=None,
            description="note",
            clear_description=True,
            command_timeout=None,
        )


def test_set_rejects_an_unusable_port(service: ProfileService) -> None:
    with pytest.raises(HostCliError) as raised:
        add(service, port=70_000)

    assert raised.value.code is ErrorCode.PROFILE_INVALID


def test_list_is_empty_before_anything_is_added(service: ProfileService) -> None:
    assert service.list() == ()


def test_list_reports_every_profile(service: ProfileService) -> None:
    add(service, NAME)
    add(service, OTHER)

    assert {view.name for view in service.list()} == {NAME, OTHER}


def test_get_fails_for_an_unknown_name(service: ProfileService) -> None:
    with pytest.raises(HostCliError) as raised:
        service.get(ProfileName(value="absent"))

    assert raised.value.code is ErrorCode.PROFILE_NOT_FOUND


def test_removing_a_profile_deletes_it_and_its_password(service: ProfileService, secrets: MemorySecretStore) -> None:
    add(service)
    service.set_password(NAME, "secret")

    service.remove(NAME)

    assert service.list() == ()
    assert secrets.values == {}


def test_removing_an_unknown_profile_fails(service: ProfileService) -> None:
    with pytest.raises(HostCliError) as raised:
        service.remove(ProfileName(value="absent"))

    assert raised.value.code is ErrorCode.PROFILE_NOT_FOUND


def test_rename_moves_settings_and_password(service: ProfileService) -> None:
    add(service, NAME, port=2222)
    service.set_password(NAME, "secret")

    service.rename(NAME, OTHER)

    view = service.get(OTHER)
    assert view.settings.port == 2222
    assert view.password_present is True
    assert service.list()[0].name == OTHER


def test_rename_leaves_no_profile_behind(service: ProfileService) -> None:
    add(service)

    service.rename(NAME, OTHER)

    with pytest.raises(HostCliError):
        service.get(NAME)


def test_rename_refuses_an_existing_destination(service: ProfileService) -> None:
    add(service, NAME)
    add(service, OTHER)

    with pytest.raises(HostCliError) as raised:
        service.rename(NAME, OTHER)

    assert raised.value.code is ErrorCode.PROFILE_CONFLICT


def test_rename_of_an_unknown_profile_fails(service: ProfileService) -> None:
    with pytest.raises(HostCliError) as raised:
        service.rename(ProfileName(value="absent"), OTHER)

    assert raised.value.code is ErrorCode.PROFILE_NOT_FOUND


def test_a_password_is_reported_as_present(service: ProfileService) -> None:
    add(service)

    service.set_password(NAME, "secret")

    assert service.get(NAME).password_present is True


def test_clearing_a_password_keeps_the_profile(service: ProfileService) -> None:
    add(service)
    service.set_password(NAME, "secret")

    service.clear_password(NAME)

    assert service.get(NAME).password_present is False


def test_storing_a_password_for_an_unknown_profile_fails(service: ProfileService) -> None:
    with pytest.raises(HostCliError) as raised:
        service.set_password(ProfileName(value="absent"), "secret")

    assert raised.value.code is ErrorCode.PROFILE_NOT_FOUND


def test_an_empty_password_is_rejected(service: ProfileService) -> None:
    add(service)

    with pytest.raises(HostCliError) as raised:
        service.set_password(NAME, "")

    assert raised.value.code is ErrorCode.INPUT_ERROR


def test_an_unavailable_credential_store_is_reported_as_such(
    service: ProfileService, secrets: MemorySecretStore
) -> None:
    add(service)
    secrets.unavailable = True

    with pytest.raises(HostCliError) as raised:
        service.set_password(NAME, "secret")

    assert raised.value.code is ErrorCode.CREDENTIAL_STORE_UNAVAILABLE


def test_the_registry_never_contains_the_password(service: ProfileService, tmp_path: Path) -> None:
    add(service)
    service.set_password(NAME, "top-secret")

    raw = (tmp_path / "profiles.json").read_text(encoding="utf-8")
    assert "top-secret" not in raw
    assert "password" not in raw


def test_settings_survive_a_reload(tmp_path: Path, secrets: MemorySecretStore) -> None:
    first = ProfileService(ProfileStore(tmp_path / "profiles.json"), PasswordStore(secrets))
    add(first, description="note", port=2222)

    reopened = ProfileService(ProfileStore(tmp_path / "profiles.json"), PasswordStore(secrets))

    restored = reopened.get(NAME).settings
    assert restored == ProfileSettings(
        host=HOST,
        user=USER,
        port=2222,
        description="note",
        command_timeout=restored.command_timeout,
    )
