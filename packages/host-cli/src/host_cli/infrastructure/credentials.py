"""Operating-system credential storage plus the transient askpass helper.

Two responsibilities live here because they are one mechanism: the keyring holds
the password, and the helper is the only way that password may reach OpenSSH
without touching argv or a persistent file.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from pathlib import Path
from typing import TYPE_CHECKING, Final

from db_cli_kit.secrets import KeyringSecretStore, SecretStoreError
from host_cli.domain.enums import ErrorCode, SshAskpass
from host_cli.domain.errors import HostCliError

if TYPE_CHECKING:
    from collections.abc import Iterator

    from db_cli_kit.profiles import ProfileName
    from db_cli_kit.secrets import SecretStore

KEYRING_SERVICE: Final[str] = "host-cli"
"""Keyring service name; the account within it is the profile name."""

ASKPASS_DIRECTORY_PREFIX: Final[str] = "host-cli-askpass-"
ASKPASS_SECRET_FILE: Final[str] = "secret.txt"
ASKPASS_SCRIPT_FILE: Final[str] = "askpass.cmd"

_ASKPASS_SCRIPT: Final[str] = (
    "@echo off\r\n"
    '"{interpreter}" -c "import os,sys;'
    "sys.stdout.write(open(os.environ['{secret}'],encoding='utf-8',newline='').read())\"\r\n"
)
"""The helper reproduces the secret file byte for byte, with no trailing newline.

``type`` was rejected on purpose: it appends the file's trailing newline and
applies its own special-character rules, corrupting a password containing ``%``
or ``&``. Reading the file inside Python also keeps the password out of the
script text and out of every command line.
"""


class PasswordStore:
    """Store and read profile passwords in the operating-system keyring."""

    def __init__(self, store: SecretStore | None = None) -> None:
        self._store: Final[SecretStore] = store or KeyringSecretStore(KEYRING_SERVICE)

    def read(self, name: ProfileName) -> str | None:
        """Return the stored password, or ``None`` when none is stored."""

        try:
            return self._store.get(name)
        except SecretStoreError as exc:
            raise HostCliError(
                ErrorCode.CREDENTIAL_STORE_UNAVAILABLE,
                "the system credential store could not be read",
            ) from exc

    def present(self, name: ProfileName) -> bool:
        """Return whether a password is stored for ``name``."""

        return self.read(name) is not None

    def write(self, name: ProfileName, password: str) -> None:
        """Store ``password`` for ``name``."""

        if not password:
            raise HostCliError(ErrorCode.INPUT_ERROR, "password must not be empty")
        try:
            self._store.set(name, password)
        except SecretStoreError as exc:
            raise HostCliError(
                ErrorCode.CREDENTIAL_STORE_UNAVAILABLE,
                "the system credential store could not be written",
            ) from exc

    def clear(self, name: ProfileName) -> None:
        """Remove the stored password for ``name``, if any."""

        try:
            self._store.delete(name)
        except SecretStoreError as exc:
            raise HostCliError(
                ErrorCode.CREDENTIAL_STORE_UNAVAILABLE,
                "the system credential store could not be updated",
            ) from exc


@dataclass(frozen=True, slots=True)
class AskpassSession:
    """The environment additions one password-backed invocation needs."""

    environment: dict[str, str] = dataclass_field(default_factory=dict)


@contextmanager
def askpass_session(password: str, interpreter: str) -> Iterator[AskpassSession]:
    """Materialise a private askpass helper and remove every trace afterwards.

    The password goes to its own file with no trailing newline and never into
    the helper script or any command line. The directory is deleted on both the
    success and the failure path, so a crash cannot leave it behind.
    """

    directory = Path(tempfile.mkdtemp(prefix=ASKPASS_DIRECTORY_PREFIX))
    try:
        secret_path = directory / ASKPASS_SECRET_FILE
        secret_path.write_bytes(password.encode("utf-8"))

        script_path = directory / ASKPASS_SCRIPT_FILE
        script_path.write_text(
            _ASKPASS_SCRIPT.format(interpreter=interpreter, secret=SshAskpass.SECRET_PATH.value),
            encoding="ascii",
            newline="",
        )

        environment = {
            SshAskpass.ASKPASS.value: str(script_path),
            SshAskpass.ASKPASS_REQUIRE.value: SshAskpass.REQUIRE_FORCE.value,
            SshAskpass.SECRET_PATH.value: str(secret_path),
        }
        yield AskpassSession(environment=environment)
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def python_interpreter() -> str:
    """Return the interpreter running this CLI, for use inside the helper."""

    return sys.executable


__all__ = [
    "ASKPASS_DIRECTORY_PREFIX",
    "ASKPASS_SCRIPT_FILE",
    "ASKPASS_SECRET_FILE",
    "KEYRING_SERVICE",
    "AskpassSession",
    "PasswordStore",
    "askpass_session",
    "python_interpreter",
]
