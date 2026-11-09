"""Concrete adapters constructed only by the CLI composition root."""

from dm_cli.adapters.profile_store import JsonProfileStore
from dm_cli.adapters.secret_store import KeyringSecretStore

__all__ = ["JsonProfileStore", "KeyringSecretStore"]
