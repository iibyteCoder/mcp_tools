"""Stream capture must be honest about bytes, bounds and encoding."""

from __future__ import annotations

import base64

from host_cli.domain.enums import StreamEncoding
from host_cli.domain.streams import capture_stream

UTF8_SAMPLE = "审计 🚀"
BINARY_SAMPLE = b"\xff\xfe\x00\x01"


def test_valid_utf8_becomes_text() -> None:
    capture = capture_stream(UTF8_SAMPLE.encode("utf-8"), 0)

    assert capture.encoding is StreamEncoding.UTF8
    assert capture.text == UTF8_SAMPLE
    assert capture.base64 is None
    assert capture.truncated is False


def test_undecodable_bytes_are_preserved_as_base64() -> None:
    capture = capture_stream(BINARY_SAMPLE, 0)

    assert capture.encoding is StreamEncoding.BINARY
    assert capture.text is None
    assert capture.base64 == base64.b64encode(BINARY_SAMPLE).decode("ascii")


def test_a_gbk_payload_is_not_guessed_at() -> None:
    gbk = "审计".encode("gbk")

    capture = capture_stream(gbk, 0)

    assert capture.encoding is StreamEncoding.BINARY
    assert capture.text is None


def test_dropped_bytes_are_counted_and_flagged() -> None:
    capture = capture_stream(b"kept", 12)

    assert capture.truncated is True
    assert capture.dropped_bytes == 12
    assert capture.bytes == 16


def test_total_length_includes_what_was_dropped() -> None:
    capture = capture_stream(b"abcdef", 4)

    assert capture.bytes == 10
    assert capture.text == "abcdef"
