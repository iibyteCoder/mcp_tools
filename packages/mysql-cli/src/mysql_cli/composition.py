"""Production dependency composition for the CLI application."""

from collections.abc import Callable
from typing import Protocol

from mysql_cli.adapters.profile_store import JsonProfileStore, ProfileStore
from mysql_cli.adapters.secret_store import KeyringSecretStore, SecretStore
from mysql_cli.application.profile import ProfileService
from mysql_cli.application.runner import CliRuntime


class ProfileStoreFactory(Protocol):
    """Construct a profile store with the CLI lock policy."""

    def __call__(self, *, lock_timeout: float) -> ProfileStore: ...


def create_runtime(
    *,
    profile_store_factory: ProfileStoreFactory = JsonProfileStore,
    secret_store_factory: Callable[[], SecretStore] = KeyringSecretStore,
) -> CliRuntime:
    """Create one CLI dependency graph without contacting a database."""

    profiles = ProfileService(
        profile_store_factory(lock_timeout=JsonProfileStore.CLI_LOCK_TIMEOUT_SECONDS),
        secret_store_factory(),
    )
    return CliRuntime(profile_service=profiles)


__all__ = ["create_runtime"]
