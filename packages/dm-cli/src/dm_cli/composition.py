"""Production dependency composition for the Dameng CLI application."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Final, Protocol

from platformdirs import user_config_path

from dm_cli.adapters.profile_store import JsonProfileStore
from dm_cli.adapters.secret_store import KeyringSecretStore
from dm_cli.application.actual_plan import ActualPlanService
from dm_cli.application.profile import ProfileService
from dm_cli.application.runner import CliRuntime
from dm_cli.application.schema_catalog import SchemaCatalogService
from dm_cli.application.schema_inspection import SchemaInspectionService
from dm_cli.application.schema_maintenance import SchemaMaintenanceService
from dm_cli.application.server_inspection import ServerInspectionService
from dm_cli.application.sql import SqlExecutionService
from dm_cli.application.validation import DmSessionValidator
from dm_client.adapters import DisqlAutotraceRunner, DmpythonDriverFactory

if TYPE_CHECKING:
    from collections.abc import Callable

    from dm_cli.ports.profile_store import ProfileStore
    from dm_cli.ports.secret_store import SecretStore
    from dm_client.ports.actual_plan import ActualPlanRunner
    from dm_client.ports.driver import DriverFactory

DB_DM_CONFIG_DIR_ENV: Final[str] = "DB_DM_CONFIG_DIR"
CONFIG_DIRECTORY_NAME: Final[str] = "db-dm"
PROFILE_FILE_NAME: Final[str] = "profiles.json"


class ProfileStoreFactory(Protocol):
    """Construct a profile store with the CLI lock policy."""

    def __call__(self, *, lock_timeout: float) -> ProfileStore: ...


def config_directory() -> Path:
    """Return the profile configuration directory, honoring the test override."""

    override = os.environ.get(DB_DM_CONFIG_DIR_ENV)
    if override is not None and override.strip():
        return Path(override).expanduser()
    return user_config_path(CONFIG_DIRECTORY_NAME)


def create_runtime(
    *,
    profile_store_factory: ProfileStoreFactory | None = None,
    secret_store_factory: Callable[[], SecretStore] | None = None,
    driver_factory: DriverFactory | None = None,
    actual_plan_runner: ActualPlanRunner | None = None,
) -> CliRuntime:
    """Create one CLI dependency graph without contacting a database."""

    profile_factory = _default_profile_store if profile_store_factory is None else profile_store_factory
    secret_factory = _default_secret_store if secret_store_factory is None else secret_store_factory
    driver = DmpythonDriverFactory() if driver_factory is None else driver_factory
    actual_runner = DisqlAutotraceRunner() if actual_plan_runner is None else actual_plan_runner
    profiles = ProfileService(
        profile_factory(lock_timeout=JsonProfileStore.CLI_LOCK_TIMEOUT_SECONDS),
        secret_factory(),
        validator=DmSessionValidator(driver),
    )
    return CliRuntime(
        profile_service=profiles,
        sql_service=SqlExecutionService(profiles, driver),
        actual_plan_service=ActualPlanService(profiles, actual_runner),
        server_inspection_service=ServerInspectionService(profiles, driver),
        schema_inspection_service=SchemaInspectionService(profiles, driver),
        schema_catalog_service=SchemaCatalogService(profiles, driver),
        schema_maintenance_service=SchemaMaintenanceService(profiles, driver),
    )


def _default_profile_store(*, lock_timeout: float) -> ProfileStore:
    return JsonProfileStore(config_directory() / PROFILE_FILE_NAME, lock_timeout=lock_timeout)


def _default_secret_store() -> SecretStore:
    return KeyringSecretStore()


__all__ = [
    "CONFIG_DIRECTORY_NAME",
    "DB_DM_CONFIG_DIR_ENV",
    "PROFILE_FILE_NAME",
    "ProfileStoreFactory",
    "config_directory",
    "create_runtime",
]
