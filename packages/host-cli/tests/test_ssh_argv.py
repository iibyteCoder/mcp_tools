"""The ssh argv must pin security posture and never rewrite the command."""

from __future__ import annotations

from pathlib import Path

import pytest

from host_cli.domain.enums import SshConfig, SshOption
from host_cli.domain.models import InvocationLimits, ProfileSettings
from host_cli.infrastructure.ssh_argv import build_argv

DEBUG_LOG = Path("session.log")
SETTINGS = ProfileSettings(host="example", user="operator", port=2222)
COMMAND_WITH_SHELL_SYNTAX = "ps aux | grep nginx && echo 'done' > /tmp/out.txt"


def _argv(*, password_available: bool = True) -> tuple[str, ...]:
    return build_argv(
        SETTINGS,
        InvocationLimits(connect_timeout=7.0),
        COMMAND_WITH_SHELL_SYNTAX,
        DEBUG_LOG,
        password_available=password_available,
    )


def test_security_options_are_all_pinned() -> None:
    argv = _argv()

    for option in SshOption:
        assert option.value in argv


def test_user_config_file_is_skipped() -> None:
    argv = _argv()

    assert argv[0] == "-F"
    assert argv[1] == SshConfig.NO_CONFIG_FILE.value


def test_the_command_stays_a_single_argument() -> None:
    argv = _argv()

    assert argv[-1] == COMMAND_WITH_SHELL_SYNTAX


def test_the_target_is_user_at_host_and_comes_last_but_one() -> None:
    argv = _argv()

    assert argv[-2] == "operator@example"


def test_the_separator_precedes_the_target() -> None:
    argv = _argv()

    assert argv[-3] == "--"


def test_the_port_comes_from_the_profile() -> None:
    argv = _argv()

    assert argv[argv.index("-p") + 1] == "2222"


def test_connect_timeout_comes_from_the_limits() -> None:
    argv = _argv()

    assert "ConnectTimeout=7" in argv


def test_a_password_allows_exactly_one_prompt() -> None:
    argv = _argv(password_available=True)

    assert SshConfig.BATCH_MODE_DISABLED.value in argv
    assert SshConfig.ONE_PASSWORD_PROMPT.value in argv


def test_no_password_disables_every_prompt() -> None:
    argv = _argv(password_available=False)

    assert SshConfig.BATCH_MODE_ENABLED.value in argv
    assert SshConfig.ONE_PASSWORD_PROMPT.value not in argv


@pytest.mark.parametrize("password_available", [True, False])
def test_the_debug_log_is_always_redirected_out_of_stderr(password_available: bool) -> None:
    argv = _argv(password_available=password_available)

    assert "-E" in argv
    assert str(DEBUG_LOG) in argv
    assert "-vv" in argv
