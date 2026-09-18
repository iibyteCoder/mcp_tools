"""Compatibility imports for the secret storage adapter."""

from mysql_cli.adapters.secret_store import KeyringSecretStore
from mysql_cli.ports.secret_store import SecretStore, SecretStoreError

__all__ = ["KeyringSecretStore", "SecretStore", "SecretStoreError"]
