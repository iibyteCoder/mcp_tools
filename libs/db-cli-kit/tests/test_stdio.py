"""Unit tests for the shared UTF-8 stdio contract."""

from __future__ import annotations

import io
import sys
from typing import TYPE_CHECKING

import pytest

from db_cli_kit.stdio import TEXT_ENCODING, enforce_utf8_stdio

if TYPE_CHECKING:
    from pytest import MonkeyPatch


def test_enforce_utf8_stdio_reconfigures_both_streams(monkeypatch: MonkeyPatch) -> None:
    stdout = io.TextIOWrapper(io.BytesIO(), encoding="cp936")
    stderr = io.TextIOWrapper(io.BytesIO(), encoding="cp936")
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)

    enforce_utf8_stdio()

    assert stdout.encoding == TEXT_ENCODING
    assert stderr.encoding == TEXT_ENCODING


def test_enforce_utf8_stdio_is_idempotent(monkeypatch: MonkeyPatch) -> None:
    stdout = io.TextIOWrapper(io.BytesIO(), encoding="cp936")
    stderr = io.TextIOWrapper(io.BytesIO(), encoding="cp936")
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)

    enforce_utf8_stdio()
    enforce_utf8_stdio()

    assert stdout.encoding == TEXT_ENCODING


def test_enforce_utf8_stdio_makes_non_ascii_writable(monkeypatch: MonkeyPatch) -> None:
    sink = io.BytesIO()
    stdout = io.TextIOWrapper(sink, encoding="cp936")
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", io.TextIOWrapper(io.BytesIO(), encoding="cp936"))

    sample = "审计🚀"
    with pytest.raises(UnicodeEncodeError):
        stdout.write(sample)
        stdout.flush()

    enforce_utf8_stdio()
    stdout.write(sample)
    stdout.flush()

    assert sink.getvalue().decode(TEXT_ENCODING) == sample


def test_enforce_utf8_stdio_raises_for_unreconfigurable_stream(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    monkeypatch.setattr(sys, "stderr", io.StringIO())

    with pytest.raises(AttributeError):
        enforce_utf8_stdio()
