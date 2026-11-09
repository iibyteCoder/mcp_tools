"""Production dependency composition for the CLI application."""

from collections.abc import Callable
from typing import Final, Protocol

from db_cli_kit.secrets import KeyringSecretStore, SecretStore
from mysql_cli.adapters.profile_store import JsonProfileStore
from mysql_cli.application.inspection import InspectionService
from mysql_cli.application.profile import MySqlSessionValidator, ProfileService
from mysql_cli.application.runner import CliRuntime
from mysql_cli.application.schema_maintenance import SchemaMaintenanceService
from mysql_cli.application.sql import SqlExecutionService
from mysql_cli.ports.profile_store import ProfileStore
from mysql_client.adapters.aiomysql import AiomysqlDriverFactory
from mysql_client.ports.driver import DriverFactory

KEYRING_SERVICE_NAME: Final[str] = "db-mysql"


class ProfileStoreFactory(Protocol):
    """Construct a profile store with the CLI lock policy."""

    def __call__(self, *, lock_timeout: float) -> ProfileStore: ...


def create_runtime(
    *,
    profile_store_factory: ProfileStoreFactory | None = None,
    secret_store_factory: Callable[[], SecretStore] | None = None,
    driver_factory: DriverFactory | None = None,
) -> CliRuntime:
    """Create one CLI dependency graph without contacting a database."""

    profile_factory = JsonProfileStore if profile_store_factory is None else profile_store_factory
    secret_factory = _default_secret_store if secret_store_factory is None else secret_store_factory
    database_factory = driver_factory or AiomysqlDriverFactory()
    profiles = ProfileService(
        profile_factory(lock_timeout=JsonProfileStore.CLI_LOCK_TIMEOUT_SECONDS),
        secret_factory(),
        MySqlSessionValidator(database_factory),
    )
    return CliRuntime(
        profile_service=profiles,
        inspection_service=InspectionService(profiles, database_factory),
        schema_maintenance_service=SchemaMaintenanceService(profiles, database_factory),
        sql_service=SqlExecutionService(profiles, database_factory),
    )


def _default_secret_store() -> SecretStore:
    return KeyringSecretStore(KEYRING_SERVICE_NAME)


__all__ = ["KEYRING_SERVICE_NAME", "create_runtime"]
