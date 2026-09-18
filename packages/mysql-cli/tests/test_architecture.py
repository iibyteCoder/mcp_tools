from __future__ import annotations

import ast
import inspect
from pathlib import Path

from mysql_cli.application.runner import execute_request

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SOURCE_ROOTS = (
    REPOSITORY_ROOT / "libs" / "mysql-client" / "src" / "mysql_client",
    REPOSITORY_ROOT / "packages" / "mysql-cli" / "src" / "mysql_cli",
)


def test_source_tree_has_no_compatibility_import_modules() -> None:
    compatibility_modules: list[Path] = []
    compatibility_marker = "Compatibility " + "import"
    for source_root in SOURCE_ROOTS:
        for source_file in source_root.rglob("*.py"):
            module = ast.parse(source_file.read_text(encoding="utf-8"))
            docstring = ast.get_docstring(module)
            if docstring is not None and docstring.startswith(compatibility_marker):
                compatibility_modules.append(source_file.relative_to(REPOSITORY_ROOT))

    assert compatibility_modules == []


def test_click_runtime_owns_the_only_sync_async_bridge() -> None:
    bridge_locations: list[Path] = []
    cli_source_root = SOURCE_ROOTS[1]
    for source_file in cli_source_root.rglob("*.py"):
        module = ast.parse(source_file.read_text(encoding="utf-8"))
        for node in ast.walk(module):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            owner = node.func.value
            if isinstance(owner, ast.Name) and owner.id == "asyncio" and node.func.attr == "run":
                bridge_locations.append(source_file.relative_to(REPOSITORY_ROOT))

    assert inspect.iscoroutinefunction(execute_request)
    assert bridge_locations == [
        Path("packages/mysql-cli/src/mysql_cli/presentation/click/runtime.py"),
    ]
