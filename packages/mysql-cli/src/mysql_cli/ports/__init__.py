"""Application-facing contracts implemented by concrete adapters."""

from mysql_cli.ports.profile_store import ProfileStore, ProfileStoreError

__all__ = ["ProfileStore", "ProfileStoreError"]
