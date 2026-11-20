"""Registry round-trips, corruption and conflict handling."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from db_cli_kit.profiles import ProfileName
from host_cli.domain.enums import ErrorCode
from host_cli.domain.errors import HostCliError
from host_cli.domain.models import ProfileRecord, ProfileRegistry, ProfileSettings
from host_cli.infrastructure.profile_store import ProfileStore

if TYPE_CHECKING:
    from pathlib import Path

NAME = ProfileName(value="dev")
SETTINGS = ProfileSettings(host="example", user="operator", port=2222, description="note")


def _store(tmp_path: Path) -> ProfileStore:
    return ProfileStore(tmp_path / "profiles.json")


def test_an_absent_registry_reads_as_empty(tmp_path: Path) -> None:
    assert _store(tmp_path).read().profiles == ()


def test_a_written_registry_round_trips(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.update(lambda registry: registry.replace(ProfileRecord(name=NAME, settings=SETTINGS)))

    restored = store.read().find(NAME)

    assert restored is not None
    assert restored.settings == SETTINGS


def test_updates_preserve_other_profiles(tmp_path: Path) -> None:
    store = _store(tmp_path)
    other = ProfileName(value="prod")
    store.update(
        lambda registry: registry.replace(ProfileRecord(name=NAME, settings=SETTINGS)).replace(
            ProfileRecord(name=other, settings=SETTINGS)
        )
    )

    assert {record.name for record in store.read().profiles} == {NAME, other}


def test_replacing_a_name_does_not_duplicate_it(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.update(lambda registry: registry.replace(ProfileRecord(name=NAME, settings=SETTINGS)))
    moved = ProfileSettings(host="moved", user="operator")

    store.update(lambda registry: registry.replace(ProfileRecord(name=NAME, settings=moved)))

    assert len(store.read().profiles) == 1
    assert store.read().find(NAME).settings.host == "moved"


def test_removal_drops_only_the_named_profile(tmp_path: Path) -> None:
    store = _store(tmp_path)
    other = ProfileName(value="prod")
    store.update(
        lambda registry: registry.replace(ProfileRecord(name=NAME, settings=SETTINGS)).replace(
            ProfileRecord(name=other, settings=SETTINGS)
        )
    )

    store.update(lambda registry: registry.remove(NAME))

    assert [record.name for record in store.read().profiles] == [other]


@pytest.mark.parametrize(
    "document",
    [
        {},
        {"profiles": "nope"},
        {"profiles": [], "extra": 1},
        {"profiles": [{"name": "dev"}]},
        {"profiles": [{"name": "dev", "settings": {}}]},
        {
            "profiles": [
                {
                    "name": "dev",
                    "settings": {"host": "", "user": "", "port": 0, "description": None, "command_timeout": 60},
                }
            ]
        },
    ],
)
def test_a_malformed_registry_is_reported_as_corrupt(tmp_path: Path, document: str) -> None:
    path = tmp_path / "profiles.json"
    path.write_text(__import__("json").dumps(document), encoding="utf-8")

    with pytest.raises(HostCliError) as raised:
        ProfileStore(path).read()

    assert raised.value.code is ErrorCode.PROFILE_REGISTRY_CORRUPT


def test_a_non_utf8_registry_is_reported_as_corrupt(tmp_path: Path) -> None:
    path = tmp_path / "profiles.json"
    path.write_bytes(b'{"profiles": "\xff\xfe"}')

    with pytest.raises(HostCliError):
        ProfileStore(path).read()


def test_the_registry_holds_no_password(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.update(lambda registry: registry.replace(ProfileRecord(name=NAME, settings=SETTINGS)))

    raw = store.path.read_text(encoding="utf-8")

    assert "password" not in raw
    assert "secret" not in raw


def test_an_empty_registry_has_no_profiles() -> None:
    assert ProfileRegistry().find(NAME) is None
