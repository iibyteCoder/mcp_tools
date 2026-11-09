"""JSON-only MySQL command line foundation."""

__version__ = "0.1.0"

from mysql_cli.adapters.profile_store import JsonProfileStore
from mysql_cli.application.profile import ProfileService
from mysql_cli.domain.profile import (
    ProfileRecord,
    ProfileRegistry,
    ProfileSelection,
    ProfileSettings,
    ProfileSettingsPatch,
)

__all__ = [
    "JsonProfileStore",
    "ProfileRecord",
    "ProfileRegistry",
    "ProfileSelection",
    "ProfileService",
    "ProfileSettings",
    "ProfileSettingsPatch",
    "__version__",
]
