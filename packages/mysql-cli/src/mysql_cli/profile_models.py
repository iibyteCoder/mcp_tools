"""Compatibility imports for profile domain models."""

from mysql_cli.domain.profile import (
    DirectoryBinding,
    ProfileName,
    ProfileRecord,
    ProfileRegistry,
    ProfileSelection,
    ProfileSelectionSource,
    ProfileSetRequest,
    ProfileSettings,
    ProfileSettingsPatch,
    RegistryErrorCode,
    normalize_directory,
)

__all__ = [
    "DirectoryBinding",
    "ProfileName",
    "ProfileRecord",
    "ProfileRegistry",
    "ProfileSelection",
    "ProfileSelectionSource",
    "ProfileSetRequest",
    "ProfileSettings",
    "ProfileSettingsPatch",
    "RegistryErrorCode",
    "normalize_directory",
]
