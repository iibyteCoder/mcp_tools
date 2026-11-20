"""Shared fixtures for the host-cli test package.

The autouse firewall below is the reason this file exists rather than staying in
a single test module: an autouse fixture declared inside a test *module* only
protects that module. Declared here, it applies to every test in the package,
which is the guarantee the incident of 2026-11-20 requires -- a danger matrix was
once pointed at a production host because nothing structurally prevented it.
"""

from __future__ import annotations

import socket
import subprocess
from typing import TYPE_CHECKING, Final

import pytest

from host_cli.domain.models import RawExecution

if TYPE_CHECKING:
    from pytest import MonkeyPatch

NO_DROPPED: Final[int] = 0
INSTANT: Final[int] = 0


@pytest.fixture(autouse=True)
def forbid_network_and_subprocess(monkeypatch: MonkeyPatch) -> None:
    """Make every outbound connection and child process fail loudly.

    Both guards raise rather than return a stub: a test that accidentally relies
    on them should fail visibly instead of silently observing fake behaviour.
    Blocking ``subprocess`` matters as much as blocking sockets -- spawning ssh
    is the other way a test could reach a real machine.
    """

    def blocked_connect(*_: object, **__: object) -> None:
        raise AssertionError("test attempted a network connection; host-cli tests stay offline")

    def blocked_spawn(*_: object, **__: object) -> None:
        raise AssertionError("test attempted to spawn a process; host-cli tests never run ssh")

    monkeypatch.setattr(socket.socket, "connect", blocked_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked_connect)
    monkeypatch.setattr(socket, "create_connection", blocked_connect)
    monkeypatch.setattr(subprocess, "Popen", blocked_spawn)
    monkeypatch.setattr(subprocess, "run", blocked_spawn)


def execution(
    *,
    exit_code: int = 0,
    stdout: bytes = b"",
    stderr: bytes = b"",
    debug_log: str = "",
    timed_out: bool = False,
    spawn_failed: bool = False,
) -> RawExecution:
    """Build one raw execution with only the fields a test cares about set."""

    return RawExecution(
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        stdout_dropped=NO_DROPPED,
        stderr_dropped=NO_DROPPED,
        duration_ms=INSTANT,
        timed_out=timed_out,
        spawn_failed=spawn_failed,
        debug_log=debug_log,
    )


__all__ = ["INSTANT", "NO_DROPPED", "execution"]
