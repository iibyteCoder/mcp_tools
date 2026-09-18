"""Compatibility imports for the profile storage adapter."""

from mysql_cli.adapters.profile_store import JsonProfileStore
from mysql_cli.ports.profile_store import ProfileStore, ProfileStoreError

__all__ = ["JsonProfileStore", "ProfileStore", "ProfileStoreError"]
