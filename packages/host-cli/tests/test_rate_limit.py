"""The per-profile rate ceiling.

This guards a different failure from every other gate: not "the command is wrong"
but "the caller will not stop". A retry loop can send hundreds of harmless
commands, and no single one of them looks dangerous.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from db_cli_kit.profiles import ProfileName
from host_cli.infrastructure.rate_limit import consume, remaining

if TYPE_CHECKING:
    from pathlib import Path

PROFILE = ProfileName(value="dev")
OTHER = ProfileName(value="prod")


def test_an_unlimited_profile_always_passes(tmp_path: Path) -> None:
    path = tmp_path / "rate.json"

    assert all(consume(path=path, profile=PROFILE, limit=0) for _ in range(50))


def test_an_unlimited_profile_writes_nothing(tmp_path: Path) -> None:
    """A profile that opted out should not pay for the accounting."""

    path = tmp_path / "rate.json"
    consume(path=path, profile=PROFILE, limit=0)

    assert not path.exists()


def test_calls_up_to_the_limit_pass(tmp_path: Path) -> None:
    path = tmp_path / "rate.json"

    results = [consume(path=path, profile=PROFILE, limit=3) for _ in range(3)]

    assert results == [True, True, True]


def test_the_call_after_the_limit_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "rate.json"
    for _ in range(3):
        consume(path=path, profile=PROFILE, limit=3)

    assert consume(path=path, profile=PROFILE, limit=3) is False


def test_a_refused_call_still_counts(tmp_path: Path) -> None:
    """Otherwise a caller could escape the ceiling by simply retrying."""

    path = tmp_path / "rate.json"
    for _ in range(3):
        consume(path=path, profile=PROFILE, limit=3)
    consume(path=path, profile=PROFILE, limit=3)

    assert consume(path=path, profile=PROFILE, limit=3) is False


def test_profiles_are_counted_separately(tmp_path: Path) -> None:
    path = tmp_path / "rate.json"
    for _ in range(3):
        consume(path=path, profile=PROFILE, limit=3)

    assert consume(path=path, profile=OTHER, limit=3) is True


def test_the_counter_survives_a_reload(tmp_path: Path) -> None:
    path = tmp_path / "rate.json"
    consume(path=path, profile=PROFILE, limit=1)

    assert consume(path=path, profile=PROFILE, limit=1) is False


def test_remaining_reports_the_headroom(tmp_path: Path) -> None:
    path = tmp_path / "rate.json"
    consume(path=path, profile=PROFILE, limit=5)
    consume(path=path, profile=PROFILE, limit=5)

    assert remaining(path=path, profile=PROFILE, limit=5) == 3


def test_remaining_never_goes_negative(tmp_path: Path) -> None:
    path = tmp_path / "rate.json"
    for _ in range(6):
        consume(path=path, profile=PROFILE, limit=2)

    assert remaining(path=path, profile=PROFILE, limit=2) == 0


def test_a_corrupt_file_does_not_lock_the_caller_out(tmp_path: Path) -> None:
    """A damaged counter must not refuse everything; the ceiling is a net, not a lock."""

    path = tmp_path / "rate.json"
    path.write_text("{not json", encoding="utf-8")

    assert consume(path=path, profile=PROFILE, limit=2) is True


def test_an_unreadable_timestamp_is_ignored(tmp_path: Path) -> None:
    path = tmp_path / "rate.json"
    path.write_text(json.dumps({PROFILE.value: ["not-a-date"]}), encoding="utf-8")

    assert consume(path=path, profile=PROFILE, limit=1) is True


def test_the_file_records_only_timestamps(tmp_path: Path) -> None:
    """The counter must not become a record of what ran; the audit log owns that."""

    path = tmp_path / "rate.json"
    consume(path=path, profile=PROFILE, limit=5)

    document = json.loads(path.read_text(encoding="utf-8"))
    assert set(document) == {PROFILE.value}
    assert isinstance(document[PROFILE.value], list)
