"""Unit tests for the versioned DM profile registry store."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from filelock import FileLock

from db_cli_kit.profiles import DirectoryBinding, ProfileName, normalize_directory
from dm_cli.adapters.profile_store import JsonProfileStore
from dm_cli.domain.profile import (
    ProfileRecord,
    ProfileRegistry,
    ProfileSettings,
    RegistryErrorCode,
)
from dm_cli.ports.profile_store import ProfileStoreError

if TYPE_CHECKING:
    from pathlib import Path


def make_registry(tmp_path: Path) -> ProfileRegistry:
    name = ProfileName(value="dev")
    return ProfileRegistry(
        profiles=(
            ProfileRecord(
                name=name,
                settings=ProfileSettings(host="127.0.0.1", user="SYSDBA", schema="APP"),
                description="local DM",
                password_present=True,
            ),
        ),
        bindings=(DirectoryBinding(path=tmp_path / "project", profile=name),),
    )


def test_round_trip_writes_the_exact_registry_document(tmp_path: Path) -> None:
    path = tmp_path / "profiles.json"
    store = JsonProfileStore(path, lock_timeout=0.0)
    registry = make_registry(tmp_path)

    store.write(registry)

    assert store.read() == registry
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document == {
        "schema": "db-dm.profile-registry",
        "version": 1,
        "profiles": [
            {
                "name": "dev",
                "settings": {
                    "host": "127.0.0.1",
                    "port": 5236,
                    "user": "SYSDBA",
                    "schema": "APP",
                    "connect_timeout": 5.0,
                    "query_timeout": 0.0,
                },
                "description": "local DM",
                "password_present": True,
            }
        ],
        "bindings": [{"path": str(normalize_directory(tmp_path / "project")), "profile": "dev"}],
    }
    assert "password" not in json.dumps(document).replace("password_present", "")


def test_missing_file_reads_as_an_empty_registry(tmp_path: Path) -> None:
    assert JsonProfileStore(tmp_path / "profiles.json", lock_timeout=0.0).read() == ProfileRegistry()


def test_update_calls_updater_once_and_persists(tmp_path: Path) -> None:
    store = JsonProfileStore(tmp_path / "profiles.json", lock_timeout=0.0)
    seen: list[ProfileRegistry] = []

    def updater(registry: ProfileRegistry) -> ProfileRegistry:
        seen.append(registry)
        return make_registry(tmp_path)

    updated = store.update(updater)

    assert len(seen) == 1
    assert updated == make_registry(tmp_path)
    assert store.read() == updated


@pytest.mark.parametrize(
    ("document", "code"),
    [
        ("{not-json}", RegistryErrorCode.CORRUPT),
        ("[]", RegistryErrorCode.CORRUPT),
        (
            json.dumps({"schema": "other", "version": 1, "profiles": [], "bindings": []}),
            RegistryErrorCode.CORRUPT,
        ),
        (
            json.dumps({"schema": "db-dm.profile-registry", "version": 2, "profiles": [], "bindings": []}),
            RegistryErrorCode.UNSUPPORTED_VERSION,
        ),
        (
            json.dumps({"schema": "db-dm.profile-registry", "version": 1, "profiles": [], "bindings": [], "x": 1}),
            RegistryErrorCode.CORRUPT,
        ),
    ],
)
def test_invalid_registry_documents_are_typed(tmp_path: Path, document: str, code: RegistryErrorCode) -> None:
    path = tmp_path / "profiles.json"
    path.write_text(document, encoding="utf-8")

    with pytest.raises(ProfileStoreError) as failure:
        JsonProfileStore(path, lock_timeout=0.0).read()

    assert failure.value.code is code


def test_duplicate_profile_names_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "profiles.json"
    store = JsonProfileStore(path, lock_timeout=0.0)
    registry = make_registry(tmp_path)
    document = json.loads(json.dumps(_document_for(registry)))
    document["profiles"].append(document["profiles"][0])
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ProfileStoreError) as failure:
        store.read()

    assert failure.value.code is RegistryErrorCode.CORRUPT


def test_lock_timeout_is_typed(tmp_path: Path) -> None:
    path = tmp_path / "profiles.json"
    store = JsonProfileStore(path, lock_timeout=0.0)
    lock = FileLock(f"{path}.lock")
    lock.acquire()
    try:
        with pytest.raises(ProfileStoreError) as failure:
            store.read()
    finally:
        lock.release()

    assert failure.value.code is RegistryErrorCode.LOCKED


def test_writes_leave_no_temporary_files(tmp_path: Path) -> None:
    path = tmp_path / "profiles.json"
    store = JsonProfileStore(path, lock_timeout=0.0)

    store.write(make_registry(tmp_path))
    store.write(ProfileRegistry())

    assert path.read_text(encoding="utf-8").endswith("\n")
    assert list(tmp_path.glob("*.tmp")) == []
    assert list(tmp_path.glob(".profiles.*")) == []


def _document_for(registry: ProfileRegistry) -> dict[str, object]:
    document = json.loads(json.dumps(_registry_payload(registry)))
    return document


def _registry_payload(registry: ProfileRegistry) -> dict[str, object]:
    record = registry.profiles[0]
    return {
        "schema": "db-dm.profile-registry",
        "version": 1,
        "profiles": [
            {
                "name": record.name.value,
                "settings": {
                    "host": record.settings.host,
                    "port": record.settings.port,
                    "user": record.settings.user,
                    "schema": record.settings.schema,
                    "connect_timeout": record.settings.connect_timeout,
                    "query_timeout": record.settings.query_timeout,
                },
                "description": record.description,
                "password_present": record.password_present,
            }
        ],
        "bindings": [],
    }
