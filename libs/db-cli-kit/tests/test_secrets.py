"""Unit tests for the keyring-backed secret store without OS keyring writes."""

from __future__ import annotations

from typing import TYPE_CHECKING

import keyring
import pytest
from keyring.errors import PasswordDeleteError

from db_cli_kit.profiles import ProfileName
from db_cli_kit.secrets import KeyringSecretStore, SecretStoreError

if TYPE_CHECKING:
    from pytest import MonkeyPatch

NAME = ProfileName(value="dev")


class FakeKeyring:
    """In-memory stand-in for the module-level keyring functions."""

    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}
        self.fail_get = False
        self.fail_set = False
        self.fail_delete = False

    def get_password(self, service: str, name: str) -> str | None:
        if self.fail_get:
            raise RuntimeError("keyring unavailable")
        return self.values.get((service, name))

    def set_password(self, service: str, name: str, password: str) -> None:
        if self.fail_set:
            raise RuntimeError("keyring unavailable")
        self.values[(service, name)] = password

    def delete_password(self, service: str, name: str) -> None:
        if self.fail_delete:
            raise RuntimeError("keyring unavailable")
        if (service, name) not in self.values:
            raise PasswordDeleteError("no stored password")
        del self.values[(service, name)]


@pytest.fixture
def fake_keyring(monkeypatch: MonkeyPatch) -> FakeKeyring:
    backend = FakeKeyring()
    monkeypatch.setattr(keyring, "get_password", backend.get_password)
    monkeypatch.setattr(keyring, "set_password", backend.set_password)
    monkeypatch.setattr(keyring, "delete_password", backend.delete_password)
    return backend


def test_store_uses_the_configured_service(fake_keyring: FakeKeyring) -> None:
    store = KeyringSecretStore("db-dm")

    store.set(NAME, "top-secret")

    assert fake_keyring.values == {("db-dm", "dev"): "top-secret"}
    assert store.get(NAME) == "top-secret"


def test_delete_is_idempotent(fake_keyring: FakeKeyring) -> None:
    store = KeyringSecretStore("db-dm")

    store.delete(NAME)
    store.set(NAME, "top-secret")
    store.delete(NAME)

    assert store.get(NAME) is None
    assert fake_keyring.values == {}


def test_empty_password_is_rejected(fake_keyring: FakeKeyring) -> None:
    store = KeyringSecretStore("db-dm")

    with pytest.raises(SecretStoreError):
        store.set(NAME, "")

    assert fake_keyring.values == {}


@pytest.mark.parametrize("operation", ["get", "set", "delete"])
def test_backend_failure_is_wrapped(fake_keyring: FakeKeyring, operation: str) -> None:
    store = KeyringSecretStore("db-dm")
    fake_keyring.fail_get = operation == "get"
    fake_keyring.fail_set = operation == "set"
    fake_keyring.fail_delete = operation == "delete"

    with pytest.raises(SecretStoreError):
        if operation == "get":
            store.get(NAME)
        elif operation == "set":
            store.set(NAME, "top-secret")
        else:
            store.delete(NAME)


def test_empty_service_is_rejected() -> None:
    with pytest.raises(ValueError):
        KeyringSecretStore("")
