"""Unit tests for dmPython value normalization."""

from __future__ import annotations

from contextlib import suppress
from datetime import date, datetime, time
from decimal import Decimal

from dm_client.adapters.dmpython.values import adapt_row, adapt_value


class FakeLob:
    def __init__(self, payload: object, *, readable: bool = True) -> None:
        self.payload = payload
        self.readable = readable
        self.closed = False

    def read(self) -> object:
        if not self.readable:
            raise RuntimeError("read failed")
        return self.payload

    def close(self) -> None:
        self.closed = True


class ReadOnlyLob:
    def read(self) -> object:
        return "payload"


class UnknownValue:
    def __str__(self) -> str:
        return "rendered"


def test_scalar_values_pass_through() -> None:
    assert adapt_value(None) is None
    assert adapt_value(True) is True
    assert adapt_value(7) == 7
    assert adapt_value(1.5) == 1.5
    assert adapt_value("text") == "text"
    assert adapt_value(b"bytes") == b"bytes"
    assert adapt_value(Decimal("1.25")) == Decimal("1.25")


def test_date_time_values_pass_through() -> None:
    day = date(2026, 11, 8)
    moment = datetime(2026, 11, 8, 10, 30, 0)
    clock = time(10, 30, 0)

    assert adapt_value(day) == day
    assert adapt_value(moment) == moment
    assert adapt_value(clock) == clock


def test_byte_containers_become_bytes() -> None:
    assert adapt_value(bytearray(b"abc")) == b"abc"
    assert adapt_value(memoryview(b"abc")) == b"abc"


def test_lob_is_read_and_closed() -> None:
    lob = FakeLob("clob text")

    assert adapt_value(lob) == "clob text"
    assert lob.closed is True


def test_binary_lob_is_read_and_closed() -> None:
    lob = FakeLob(b"blob bytes")

    assert adapt_value(lob) == b"blob bytes"
    assert lob.closed is True


def test_lob_without_close_still_reads() -> None:
    assert adapt_value(ReadOnlyLob()) == "payload"


def test_lob_close_runs_when_read_fails() -> None:
    lob = FakeLob("unused", readable=False)

    with suppress(RuntimeError):
        adapt_value(lob)

    assert lob.closed is True


def test_list_and_mapping_values_are_recursive() -> None:
    assert adapt_value([1, "two", None]) == [1, "two", None]
    assert adapt_value({"a": 1, "b": b"x"}) == {"a": 1, "b": b"x"}


def test_unknown_value_uses_last_resort_string() -> None:
    assert adapt_value(UnknownValue()) == "rendered"


def test_adapt_row_converts_every_value() -> None:
    row = adapt_row([1, bytearray(b"x"), FakeLob("lob")])

    assert row == (1, b"x", "lob")
