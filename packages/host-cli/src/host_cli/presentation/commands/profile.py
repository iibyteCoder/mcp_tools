"""The ``profile`` command group."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import click

from host_cli.application.guard import record_executed
from host_cli.application.profile_service import ProfileService
from host_cli.application.run_service import validate_profile
from host_cli.domain.enums import OUTCOME_ERROR_CODES
from host_cli.domain.errors import HostCliError
from host_cli.domain.models import InvocationLimits
from host_cli.presentation.failures import argument_failure, report, report_failure
from host_cli.presentation.params import PORT_RANGE, POSITIVE_SECONDS, PROFILE_NAME
from host_cli.presentation.rendering import profile_document, profiles_document, run_document

if TYPE_CHECKING:
    from db_cli_kit.profiles import ProfileName

VALIDATION_LOG_NAME = "validate.log"
"""Name of the per-invocation ssh debug log for a validation run."""


@click.group("profile")
def profile_group() -> None:
    """Manage the saved hosts. Passwords live in the OS credential store."""


@profile_group.command("list")
def list_profiles() -> None:
    """Show every saved profile."""

    report(profiles_document(_service().list()))


@profile_group.command("show")
@click.argument("name", type=PROFILE_NAME)
def show_profile(name: ProfileName) -> None:
    """Show one saved profile, without its password."""

    report(profile_document(_service().get(name)))


@profile_group.command("set")
@click.argument("name", type=PROFILE_NAME)
@click.option("--host", default=None, help="Host name or address.")
@click.option("--user", default=None, help="Login account on the host.")
@click.option("--port", type=PORT_RANGE, default=None, help="TCP port; defaults to 22.")
@click.option("--description", default=None, help="Free-form note about the machine.")
@click.option("--no-description", is_flag=True, help="Remove the note.")
@click.option(
    "--command-timeout",
    type=POSITIVE_SECONDS,
    default=None,
    help="Default command bound in seconds.",
)
@click.option(
    "--read-only",
    "read_only",
    flag_value=True,
    default=None,
    help="Refuse anything that is not inspection.",
)
@click.option(
    "--writable",
    "read_only",
    flag_value=False,
    help="Allow changes again, undoing --read-only.",
)
@click.option(
    "--max-commands-per-minute",
    type=click.IntRange(min=0),
    default=None,
    help="Rate ceiling; 0 means unlimited.",
)
@click.option(
    "--requires-approval",
    "requires_approval",
    flag_value=True,
    default=None,
    help="Refuse every run until a token from run --request-approval is supplied.",
)
@click.option(
    "--no-approval",
    "requires_approval",
    flag_value=False,
    help="Stop requiring an approval for each run.",
)
def set_profile(
    name: ProfileName,
    host: str | None,
    user: str | None,
    port: int | None,
    description: str | None,
    no_description: bool,
    command_timeout: float | None,
    read_only: bool | None,
    max_commands_per_minute: int | None,
    requires_approval: bool | None,
) -> None:
    """Create or update one profile; omitted fields keep their stored value."""

    if description is not None and no_description:
        argument_failure("--description and --no-description cannot be combined")
    view = _service().set(
        name,
        host=host,
        user=user,
        port=port,
        description=description,
        clear_description=no_description,
        command_timeout=command_timeout,
        read_only=read_only,
        max_commands_per_minute=max_commands_per_minute,
        requires_approval=requires_approval,
    )
    report(profile_document(view))


@profile_group.command("rename")
@click.argument("old", type=PROFILE_NAME)
@click.argument("new", type=PROFILE_NAME)
def rename_profile(old: ProfileName, new: ProfileName) -> None:
    """Rename one profile, carrying its settings and stored password across."""

    report(profile_document(_service().rename(old, new)))


@profile_group.command("remove")
@click.argument("name", type=PROFILE_NAME)
def remove_profile(name: ProfileName) -> None:
    """Delete one profile and the password stored for it."""

    _service().remove(name)
    report({"removed": True, "profile": name.value})


@profile_group.command("set-password")
@click.argument("name", type=PROFILE_NAME)
@click.option("--password-stdin", is_flag=True, help="Read the password from standard input.")
def set_password(name: ProfileName, password_stdin: bool) -> None:
    """Store the login password for one profile."""

    if not password_stdin:
        argument_failure("--password-stdin is required: a password is never accepted as an argument")
    service = _service()
    service.set_password(name, _read_password())
    report({"profile": name.value, "password_present": True})


@profile_group.command("clear-password")
@click.argument("name", type=PROFILE_NAME)
def clear_password(name: ProfileName) -> None:
    """Forget the stored password, leaving key authentication available."""

    _service().clear_password(name)
    report({"profile": name.value, "password_present": False})


@profile_group.command("validate")
@click.argument("name", type=PROFILE_NAME)
@click.option(
    "--timeout",
    type=POSITIVE_SECONDS,
    default=None,
    help="Override the command bound in seconds.",
)
def validate_one_profile(name: ProfileName, timeout: float | None) -> None:
    """Check that a profile can reach, trust and authenticate to its host.

    Sends ``true``: the smallest command that exercises the whole path while
    changing nothing on the machine.
    """

    service = _service()
    record = service.record(name)
    limits = InvocationLimits(command_timeout=timeout if timeout is not None else record.settings.command_timeout)

    from host_cli.infrastructure.credentials import PasswordStore

    with tempfile.TemporaryDirectory(prefix="host-cli-") as workspace:
        result = validate_profile(
            record,
            limits=limits,
            passwords=PasswordStore(),
            debug_log_path=Path(workspace) / VALIDATION_LOG_NAME,
        )

    data = run_document(result, audit_status=record_executed(result, record))
    if result.outcome.kind.is_success:
        report(data)
        return
    report_failure(
        data,
        HostCliError(
            OUTCOME_ERROR_CODES[result.outcome.kind],
            result.outcome.kind.value.replace("_", " "),
            host_key_problem=result.outcome.host_key_problem,
            fingerprint=result.fingerprint,
            debug_log_tail=result.debug_log_tail,
        ),
    )


def _service() -> ProfileService:
    """Build the profile service for one invocation."""

    from host_cli.infrastructure.credentials import PasswordStore
    from host_cli.infrastructure.profile_store import ProfileStore

    return ProfileService(ProfileStore(), PasswordStore())


def _read_password() -> str:
    """Read a password from standard input as raw bytes.

    Reading the buffer rather than the text stream avoids the host code page
    silently rewriting a non-ASCII password.
    """

    raw = sys.stdin.buffer.read()
    try:
        password = raw.decode("utf-8")
    except UnicodeDecodeError:
        argument_failure("the password is not valid UTF-8")
        raise AssertionError("argument_failure always raises") from None
    return password.rstrip("\r\n")


__all__ = ["VALIDATION_LOG_NAME", "profile_group"]
