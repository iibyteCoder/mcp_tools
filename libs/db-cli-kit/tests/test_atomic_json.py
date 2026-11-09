"""Unit tests for the atomic JSON store."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from filelock import FileLock

from db_cli_kit.atomic_json import AtomicJsonError, AtomicJsonErrorReason, AtomicJsonStore

if TYPE_CHECKING:
    from db_cli_kit.json_codec import JsonObject


def test_read_returns_none_for_missing_file(tmp_path: Path) -> None:
    store = AtomicJsonStore(tmp_path / "profiles.json", 0.0)

    assert store.read() is None


def test_write_then_read_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "profiles.json"
    store = AtomicJsonStore(path, 1.0)

    store.write({"schema": "test", "items": [1, 2]})

    assert store.read() == {"schema": "test", "items": [1, 2]}
    assert path.read_text(encoding="utf-8").endswith("\n")
    assert list(tmp_path.glob("*.tmp")) == []


def test_update_observes_current_document(tmp_path: Path) -> None:
    store = AtomicJsonStore(tmp_path / "profiles.json", 1.0)

    first = store.update(lambda document: {"count": 1} if document is None else document)
    second = store.update(lambda document: {"count": int(document["count"]) + 1} if document is not None else {})

    assert first == {"count": 1}
    assert second == {"count": 2}
    assert store.read() == {"count": 2}


def test_update_error_does_not_write(tmp_path: Path) -> None:
    path = tmp_path / "profiles.json"
    store = AtomicJsonStore(path, 1.0)
    store.write({"value": "original"})

    def fail(document: JsonObject | None) -> JsonObject:
        del document
        raise RuntimeError("updater failed")

    with pytest.raises(RuntimeError):
        store.update(fail)

    assert store.read() == {"value": "original"}


def test_corrupt_document_is_typed(tmp_path: Path) -> None:
    path = tmp_path / "profiles.json"
    path.write_text("{not-json}", encoding="utf-8")

    with pytest.raises(AtomicJsonError) as failure:
        AtomicJsonStore(path, 0.0).read()

    assert failure.value.reason is AtomicJsonErrorReason.CORRUPT


def test_non_object_document_is_typed(tmp_path: Path) -> None:
    path = tmp_path / "profiles.json"
    path.write_text("[1, 2]", encoding="utf-8")

    with pytest.raises(AtomicJsonError) as failure:
        AtomicJsonStore(path, 0.0).read()

    assert failure.value.reason is AtomicJsonErrorReason.CORRUPT


def test_unreadable_file_is_typed_as_io(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "profiles.json"
    path.write_text('{"value": 1}', encoding="utf-8")

    def unreadable(self: Path, *args: object, **kwargs: object) -> str:
        raise OSError("access denied")

    monkeypatch.setattr(Path, "read_text", unreadable)

    with pytest.raises(AtomicJsonError) as failure:
        AtomicJsonStore(path, 0.0).read()

    assert failure.value.reason is AtomicJsonErrorReason.IO


def test_lock_timeout_is_typed(tmp_path: Path) -> None:
    path = tmp_path / "profiles.json"
    store = AtomicJsonStore(path, 0.0)
    lock = FileLock(str(store.lock_path))
    lock.acquire()
    try:
        with pytest.raises(AtomicJsonError) as failure:
            store.write({"value": 1})
    finally:
        lock.release()

    assert failure.value.reason is AtomicJsonErrorReason.LOCKED
