"""Conversion of raw bytes into the JSON stream representation."""

from __future__ import annotations

import base64

from host_cli.domain.enums import StreamEncoding
from host_cli.domain.models import StreamCapture


def capture_stream(raw: bytes, dropped: int) -> StreamCapture:
    """Represent one raw stream as strict UTF-8 text, or as base64 when it is not.

    Decoding is strict on purpose. A silent replacement character would claim
    the tool understood bytes it did not, so undecodable content is reported as
    ``binary`` with the exact bytes preserved in base64.
    """

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return StreamCapture(
            encoding=StreamEncoding.BINARY,
            text=None,
            base64=base64.b64encode(raw).decode("ascii"),
            bytes=len(raw) + dropped,
            dropped_bytes=dropped,
        )
    return StreamCapture(
        encoding=StreamEncoding.UTF8,
        text=text,
        base64=None,
        bytes=len(raw) + dropped,
        dropped_bytes=dropped,
    )


__all__ = ["capture_stream"]
