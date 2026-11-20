"""Proof that the package-wide offline firewall actually fires.

The firewall itself lives in ``conftest.py`` as an autouse fixture, so every test
in this package runs under it. This module exists to assert that the mechanism
works: a guard that silently does nothing is worse than no guard, because it
looks like protection.
"""

from __future__ import annotations

import socket
import subprocess
from pathlib import Path

import pytest

FORBIDDEN_FRAGMENTS = ("192.168.", "10.10.10.", "172.16.", ".internal", ".local")
"""Fragments that only appear in a real target, never in a fixture.

Deliberately patterns rather than the exact addresses and credentials from the
2026-11-20 incident: this file is committed, and a blocklist that quoted the real
host or password would leak the very thing it exists to keep out of tests.
Matching private-range prefixes and internal hostname suffixes catches the
realistic mistake -- someone pasting a working command into a test -- without
reproducing it here.

``example.test`` is the reserved name fixtures use, so it is not in the list.
"""


def test_the_firewall_blocks_socket_connections() -> None:
    """A test that tries to reach a host must fail, not connect."""

    with pytest.raises(AssertionError, match="network connection"):
        socket.create_connection(("127.0.0.1", 9), timeout=0.01)


def test_the_firewall_blocks_raw_socket_connect() -> None:
    """The lower-level entry point is guarded too, not just the helper."""

    with pytest.raises(AssertionError, match="network connection"):
        socket.socket().connect(("127.0.0.1", 9))


def test_the_firewall_blocks_subprocess_spawning() -> None:
    """Spawning a process is how ssh would be reached, so it is blocked."""

    with pytest.raises(AssertionError, match="spawn a process"):
        subprocess.run(["echo", "should-not-run"], check=False)


def test_no_test_module_names_a_real_host() -> None:
    """Fail while a leaked target is still text, not after it has connected.

    A runtime guard fires too late if someone copies a real address into a
    fixture, because by then the intent to use it is already committed.
    """

    package_root = Path(__file__).resolve().parent
    offenders: list[str] = []
    for source in package_root.glob("test_*.py"):
        if source.name == Path(__file__).name:
            continue
        text = source.read_text(encoding="utf-8")
        offenders.extend(f"{source.name}: {fragment}" for fragment in FORBIDDEN_FRAGMENTS if fragment in text)

    assert not offenders, f"tests reference real targets: {offenders}"
