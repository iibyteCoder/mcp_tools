"""Compatibility imports for the secret storage adapter."""

from mysql_cli.adapters.secret_store import KeyringSecretStore, SecretStore, SecretStoreError

__all__ = ["KeyringSecretStore", "SecretStore", "SecretStoreError"]
