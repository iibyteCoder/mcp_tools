"""Test-only import path setup for the local mysql-client dependency."""

from __future__ import annotations

import sys
from pathlib import Path


def pytest_sessionstart(session: object) -> None:
    """Make the sibling local dependency importable without installing it."""

    del session
    repository_root = Path(__file__).resolve().parents[3]
    mysql_client_source = repository_root / "libs" / "mysql-client" / "src"
    sys.path.insert(0, str(mysql_client_source))
