"""Credential storage contract for DM profile passwords.

The protocol and its error type live in :mod:`db_cli_kit.secrets` so every
``db-*`` CLI shares one definition.
"""

from db_cli_kit.secrets import SecretStore, SecretStoreError

__all__ = ["SecretStore", "SecretStoreError"]
