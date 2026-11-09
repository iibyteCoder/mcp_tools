"""Architecture tests for the database-neutral CLI kit."""

from __future__ import annotations

import ast
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src" / "db_cli_kit"
FORBIDDEN_TOP_LEVEL_MODULES = {
    "click",
    "dmPython",
    "dm_cli",
    "dm_client",
    "mysql_cli",
    "redis_cli",
}


def test_kit_has_no_cli_or_database_driver_imports() -> None:
    violations: list[str] = []
    for source_file in SOURCE_ROOT.rglob("*.py"):
        module = ast.parse(source_file.read_text(encoding="utf-8"))
        for node in ast.walk(module):
            roots: list[str] = []
            if isinstance(node, ast.Import):
                roots = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module is not None:
                roots = [node.module.split(".")[0]]
            for root in roots:
                if root in FORBIDDEN_TOP_LEVEL_MODULES:
                    violations.append(f"{source_file.relative_to(SOURCE_ROOT)}: {root}")

    assert violations == []
