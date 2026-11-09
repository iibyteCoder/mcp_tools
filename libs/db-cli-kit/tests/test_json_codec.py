"""Unit tests for the explicit JSON codec."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from pathlib import Path

import pytest

from db_cli_kit.json_codec import (
    JsonDocumentError,
    encode_json_document,
    is_json_array,
    is_json_object,
    is_json_value,
    parse_json_document,
)


class Color(str, Enum):
    RED = "red"


@dataclass(frozen=True)
class Sample:
    decimal: Decimal
    day: date
    moment: datetime
    clock: time
    binary: bytes
    color: Color
    path: Path
    items: tuple[int, ...]


def test_encode_supports_contract_value_types() -> None:
    sample = Sample(
        decimal=Decimal("12.340"),
        day=date(2026, 11, 8),
        moment=datetime(2026, 11, 8, 18, 40),
        clock=time(18, 40, 1),
        binary=b"\x00\xff",
        color=Color.RED,
        path=Path("data") / "sample.json",
        items=(1, 2),
    )

    document = json.loads(encode_json_document(sample))

    assert document["decimal"] == "12.340"
    assert document["day"] == "2026-11-08"
    assert document["moment"] == "2026-11-08T18:40:00"
    assert document["clock"] == "18:40:01"
    assert document["binary"] == base64.b64encode(b"\x00\xff").decode("ascii")
    assert document["color"] == "red"
    assert document["path"] == str(Path("data") / "sample.json")
    assert document["items"] == [1, 2]


def test_encode_ends_with_exactly_one_newline() -> None:
    encoded = encode_json_document({"ok": True})

    assert encoded == '{"ok":true}\n'


def test_encode_rejects_values_without_an_explicit_mapping() -> None:
    with pytest.raises(TypeError):
        encode_json_document(object())

    with pytest.raises(TypeError):
        encode_json_document({1: "value"})


def test_decode_round_trips_objects_and_arrays() -> None:
    document = {"items": [1, 2.5, None, True, "text"], "nested": {"empty": []}}

    assert parse_json_document(json.dumps(document)) == document
    assert is_json_object({"a": 1})
    assert is_json_array([1])
    assert is_json_value({"a": [1, None]})


def test_decode_rejects_non_finite_constants() -> None:
    with pytest.raises(JsonDocumentError):
        parse_json_document('{"value": NaN}')

    with pytest.raises(JsonDocumentError):
        parse_json_document("{not-json}")

    with pytest.raises(JsonDocumentError):
        parse_json_document('{"value": 1} trailing')
