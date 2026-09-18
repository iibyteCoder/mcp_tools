"""JSON-only MySQL command line foundation."""

__version__ = "0.1.0"

from mysql_command.profile_models import (
    DirectoryBinding,
    ProfileName,
    ProfileRecord,
    ProfileRegistry,
    ProfileSelection,
    ProfileSettings,
    ProfileSettingsPatch,
)
from mysql_command.profile_service import ProfileService
from mysql_command.profile_store import JsonProfileStore
from mysql_command.secret_store import KeyringSecretStore

__all__ = [
    "DirectoryBinding",
    "JsonProfileStore",
    "KeyringSecretStore",
    "ProfileName",
    "ProfileRecord",
    "ProfileRegistry",
    "ProfileSelection",
    "ProfileService",
    "ProfileSettings",
    "ProfileSettingsPatch",
    "__version__",
]
