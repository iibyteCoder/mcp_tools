"""Locked, atomic JSON document persistence shared by the CLI tools."""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import contextmanager
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

from filelock import FileLock, Timeout

from db_cli_kit.json_codec import JsonDocumentError, JsonObject, is_json_object, parse_json_document

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator


class AtomicJsonErrorReason(str, Enum):
    """Stable failure categories for an atomic JSON store."""

    CORRUPT = "corrupt"
    LOCKED = "locked"
    IO = "io"


class AtomicJsonError(RuntimeError):
    """A typed, document-agnostic atomic JSON persistence failure."""

    def __init__(self, reason: AtomicJsonErrorReason, message: str) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message


class AtomicJsonStore:
    """Read and replace one JSON object under a process-safe file lock."""

    def __init__(self, path: Path, lock_timeout: float) -> None:
        if lock_timeout < 0:
            raise ValueError("lock timeout must not be negative")
        self.path = path
        self.lock_path = Path(f"{path}.lock")
        self.lock_timeout = lock_timeout

    def read(self) -> JsonObject | None:
        """Return the stored object, or ``None`` when the file does not exist."""

        with self._locked():
            return self._read_unlocked()

    def write(self, document: JsonObject) -> None:
        """Replace the stored document atomically."""

        with self._locked():
            self._write_unlocked(document)

    def update(self, updater: Callable[[JsonObject | None], JsonObject]) -> JsonObject:
        """Read, transform and replace the document under one lock acquisition."""

        with self._locked():
            updated = updater(self._read_unlocked())
            self._write_unlocked(updated)
            return updated

    @contextmanager
    def _locked(self) -> Iterator[None]:
        lock = FileLock(str(self.lock_path), timeout=self.lock_timeout)
        try:
            lock.acquire()
        except Timeout as exc:
            raise AtomicJsonError(AtomicJsonErrorReason.LOCKED, "JSON document is locked") from exc
        try:
            yield
        finally:
            lock.release()

    def _read_unlocked(self) -> JsonObject | None:
        if not self.path.exists():
            return None
        try:
            text = self.path.read_text(encoding="utf-8")
        except UnicodeError as exc:
            raise AtomicJsonError(AtomicJsonErrorReason.CORRUPT, "JSON document is not valid UTF-8") from exc
        except OSError as exc:
            raise AtomicJsonError(AtomicJsonErrorReason.IO, "JSON document could not be read") from exc
        try:
            loaded = parse_json_document(text)
        except JsonDocumentError as exc:
            raise AtomicJsonError(AtomicJsonErrorReason.CORRUPT, "JSON document is unreadable") from exc
        if not is_json_object(loaded):
            raise AtomicJsonError(AtomicJsonErrorReason.CORRUPT, "JSON document must be an object")
        return loaded

    def _write_unlocked(self, document: JsonObject) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary_name = tempfile.mkstemp(prefix=f".{self.path.stem}.", suffix=".tmp", dir=self.path.parent)
            temporary_path = Path(temporary_name)
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                    json.dump(document, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
                    stream.write("\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary_path, self.path)
            finally:
                temporary_path.unlink(missing_ok=True)
        except (OSError, TypeError, ValueError) as exc:
            raise AtomicJsonError(AtomicJsonErrorReason.IO, "JSON document could not be written") from exc


__all__ = ["AtomicJsonError", "AtomicJsonErrorReason", "AtomicJsonStore"]
