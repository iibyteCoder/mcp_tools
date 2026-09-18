"""Compatibility imports for the profile storage adapter."""

from mysql_cli.adapters.profile_store import JsonProfileStore, ProfileStore, ProfileStoreError

__all__ = ["JsonProfileStore", "ProfileStore", "ProfileStoreError"]
