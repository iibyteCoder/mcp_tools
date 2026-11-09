"""Unit tests for reusable profile identity values."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from db_cli_kit.profiles import (
    PROFILE_NAME_PATTERN,
    DirectoryBinding,
    ProfileName,
    normalize_directory,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("value", ["a", "dev", "lot-01", "A.B_c-9", "x" * 64])
def test_profile_name_accepts_contract_pattern(value: str) -> None:
    name = ProfileName(value=value)

    assert name.value == value
    assert str(name) == value
    assert repr(name) == f"ProfileName(value={value!r})"
    assert PROFILE_NAME_PATTERN.fullmatch(value) is not None


@pytest.mark.parametrize("value", ["", "-dev", ".dev", "_dev", "a b", "a/b", "x" * 65, "配置"])
def test_profile_name_rejects_invalid_values(value: str) -> None:
    with pytest.raises(ValueError):
        ProfileName(value=value)


def test_directory_binding_normalizes_path_and_keeps_profile(tmp_path: Path) -> None:
    raw = tmp_path / "nested" / ".." / "project"
    binding = DirectoryBinding(path=raw, profile=ProfileName(value="dev"))

    assert binding.path == normalize_directory(raw)
    assert binding.profile == ProfileName(value="dev")


def test_normalize_directory_does_not_require_existence(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"

    assert normalize_directory(missing) == missing.resolve()
