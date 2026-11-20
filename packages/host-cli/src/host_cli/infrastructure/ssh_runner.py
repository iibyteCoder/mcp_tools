"""Running one ssh process, capturing both streams under a hard time bound."""

from __future__ import annotations

import os
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import IO, TYPE_CHECKING, Final

from host_cli.domain.enums import SshBinary, SshExitCode
from host_cli.domain.models import RawExecution

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from host_cli.domain.models import InvocationLimits
    from host_cli.infrastructure.ssh_argv import SshPlan

READ_CHUNK_BYTES: Final[int] = 65_536
"""Chunk size when draining a pipe; large enough to keep syscall overhead low."""

THREAD_JOIN_SECONDS: Final[float] = 5.0
"""How long to wait for a reader thread after the process is gone."""

CREATE_NO_WINDOW: Final[int] = 0x0800_0000
"""Stop the child from flashing a console window when the parent has none."""

TASKKILL_TREE_ARGUMENTS: Final[tuple[str, ...]] = ("/T", "/F")
"""Terminate the whole process tree, forcefully.

``/T`` is the part that matters: killing only ssh would leave the connection's
children behind, one leak per timeout.
"""


@dataclass(slots=True)
class _BoundedCapture:
    """Collect one stream up to a byte bound, counting everything beyond it."""

    limit: int
    data: bytearray
    dropped: int = 0

    def append(self, chunk: bytes) -> None:
        room = self.limit - len(self.data)
        if room >= len(chunk):
            self.data.extend(chunk)
            return
        if room > 0:
            self.data.extend(chunk[:room])
        self.dropped += len(chunk) - max(room, 0)

    def start(self, stream: IO[bytes] | None) -> threading.Thread:
        """Drain ``stream`` on a worker thread and return that thread."""

        def pump() -> None:
            if stream is None:
                return
            try:
                for chunk in iter(lambda: stream.read(READ_CHUNK_BYTES), b""):
                    self.append(chunk)
            finally:
                stream.close()

        thread = threading.Thread(target=pump, daemon=True)
        thread.start()
        return thread


def execute(
    plan: SshPlan,
    limits: InvocationLimits,
    *,
    ssh_executable: str = SshBinary.SSH.value,
    extra_environment: Mapping[str, str] | None = None,
) -> RawExecution:
    """Run the plan and report what was observed, without interpreting it.

    Each stream is drained on its own thread so a chatty command can never
    deadlock on a full pipe, and so the byte bound limits what is *kept* rather
    than what is *read*: the remote process always runs to its own conclusion.
    """

    started = time.monotonic()
    try:
        process = _spawn(plan, ssh_executable, extra_environment)
    except FileNotFoundError:
        return _spawn_failure(started)
    if process is None:  # pragma: no cover - defensive, Popen raises instead
        return _spawn_failure(started)

    stdout = _BoundedCapture(limits.max_stream_bytes, bytearray())
    stderr = _BoundedCapture(limits.max_stream_bytes, bytearray())
    readers = (stdout.start(process.stdout), stderr.start(process.stderr))

    timed_out = not _wait(process, limits.command_timeout)
    for reader in readers:
        reader.join(THREAD_JOIN_SECONDS)

    return RawExecution(
        exit_code=_as_signed_exit_code(process.returncode),
        stdout=bytes(stdout.data),
        stderr=bytes(stderr.data),
        stdout_dropped=stdout.dropped,
        stderr_dropped=stderr.dropped,
        duration_ms=_elapsed_ms(started),
        timed_out=timed_out,
        spawn_failed=False,
        debug_log=_read_debug_log(plan.debug_log_path),
    )


def _as_signed_exit_code(returncode: int | None) -> int:
    """Normalise a process exit code to the signed value OpenSSH means.

    Windows reports exit codes as unsigned 32-bit, so OpenSSH's ``-1`` (used
    after a relayed ``exit-signal``) arrives as ``4294967295``. Classification
    compares against the signed constant, so the sign has to be restored here
    rather than in every branch.
    """

    if returncode is None:
        return SshExitCode.KILLED_BY_SIGNAL
    unsigned = returncode & 0xFFFF_FFFF
    return unsigned - 0x1_0000_0000 if unsigned >= 0x8000_0000 else unsigned


def _spawn(
    plan: SshPlan,
    ssh_executable: str,
    extra_environment: Mapping[str, str] | None,
) -> subprocess.Popen[bytes]:
    """Start the ssh process with a closed stdin, both pipes captured, no console.

    stdin is a pipe closed immediately rather than ``DEVNULL``, because the two
    are not equivalent: measured against OpenSSH for Windows, ``DEVNULL`` leaves
    the remote side waiting forever on a command that reads stdin, while a closed
    pipe delivers the EOF that R3 requires. A remote ``cat`` proves it -- it
    exits on a closed pipe and hangs on ``DEVNULL``.

    ``extra_environment`` carries the askpass variables when a password exists;
    it is layered over the inherited environment because OpenSSH still needs
    ``PATH`` and the rest of the caller's surroundings to resolve its own files.
    """

    environment = None if extra_environment is None else {**os.environ, **extra_environment}
    process = subprocess.Popen(
        [ssh_executable, *plan.argv],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
        creationflags=CREATE_NO_WINDOW,
    )
    if process.stdin is not None:
        process.stdin.close()
    return process


def _wait(process: subprocess.Popen[bytes], timeout: float) -> bool:
    """Wait for exit, terminating the process tree on expiry."""

    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_tree(process)
        return False
    return True


def _kill_tree(process: subprocess.Popen[bytes]) -> None:
    """Terminate ssh and its children, escalating if the process lingers."""

    subprocess.run(
        [SshBinary.TASKKILL.value, "/PID", str(process.pid), *TASKKILL_TREE_ARGUMENTS],
        capture_output=True,
        check=False,
        creationflags=CREATE_NO_WINDOW,
    )
    try:
        process.wait(timeout=THREAD_JOIN_SECONDS)
    except subprocess.TimeoutExpired:  # pragma: no cover - taskkill already forces
        process.kill()


def _spawn_failure(started: float) -> RawExecution:
    """Report the case where no ssh client could be started at all."""

    return RawExecution(
        exit_code=0,
        stdout=b"",
        stderr=b"",
        stdout_dropped=0,
        stderr_dropped=0,
        duration_ms=_elapsed_ms(started),
        timed_out=False,
        spawn_failed=True,
        debug_log="",
    )


def _read_debug_log(path: Path) -> str:
    """Return the ssh debug log, or an empty string when it was not written."""

    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _elapsed_ms(started: float) -> int:
    """Return whole milliseconds elapsed since ``started``."""

    return int((time.monotonic() - started) * 1000)


__all__ = [
    "CREATE_NO_WINDOW",
    "READ_CHUNK_BYTES",
    "TASKKILL_TREE_ARGUMENTS",
    "THREAD_JOIN_SECONDS",
    "execute",
]
