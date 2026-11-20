"""Process-level text stream contract shared by every command line tool."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Final, cast

if TYPE_CHECKING:
    import io

TEXT_ENCODING: Final[str] = "utf-8"
"""Encoding every CLI uses for text streams, independent of the host locale."""


def enforce_utf8_stdio() -> None:
    """Make both standard text streams speak UTF-8 for this process.

    Every CLI calls this once at the start of its ``main``. Without it the
    streams inherit the locale encoding, so redirected output is mangled on a
    non-UTF-8 host (``cp936`` here) and characters outside that code page raise
    ``UnicodeEncodeError`` instead of printing.

    The call is deliberately unconditional: a stream that cannot be
    reconfigured means the process was embedded in an unusual host, and that is
    a programming error worth raising rather than silently degrading.
    """

    cast("io.TextIOWrapper", sys.stdout).reconfigure(encoding=TEXT_ENCODING)
    cast("io.TextIOWrapper", sys.stderr).reconfigure(encoding=TEXT_ENCODING)


__all__ = ["TEXT_ENCODING", "enforce_utf8_stdio"]
