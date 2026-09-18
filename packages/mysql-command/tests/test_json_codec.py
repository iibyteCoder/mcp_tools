"""Tests for explicit JSON serialization rules."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from mysql_command.json_codec import encode_json_document


@dataclass(frozen=True, slots=True, kw_only=True)
class CodecFixture:
    """Values exercising the supported non-primitive conversions."""

    path: Path
    timestamp: datetime
    amount: Decimal
    payload: bytes


def test_codec_handles_explicit_supported_values() -> None:
    encoded = encode_json_document(
        CodecFixture(
            path=Path("config.json"),
            timestamp=datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc),
            amount=Decimal("12.50"),
            payload=b"secret-free-bytes",
        )
    )

    decoded = json.loads(encoded)
    assert decoded["path"] == "config.json"
    assert decoded["timestamp"] == "2026-09-18T12:00:00+00:00"
    assert decoded["amount"] == "12.50"
    assert decoded["payload"] == "c2VjcmV0LWZyZWUtYnl0ZXM="
