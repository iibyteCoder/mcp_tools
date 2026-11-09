"""Architecture tests for the Batch 2b Dameng CLI tree."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SOURCE_ROOT = REPOSITORY_ROOT / "packages" / "dm-cli" / "src" / "dm_cli"
STDLIB_MODULES = frozenset(sys.stdlib_module_names)
DMPYTHON_MODULE = "dmPython"
DM_CLIENT_ADAPTERS_MODULE = "dm_client.adapters"


def imported_modules(source_file: Path) -> list[tuple[str, int]]:
    module = ast.parse(source_file.read_text(encoding="utf-8"))
    imports: list[tuple[str, int]] = []
    for node in ast.walk(module):
        if isinstance(node, ast.Import):
            imports.extend((alias.name, 0) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append((node.module or "", node.level))
    return imports


def is_stdlib_or(module: str, prefixes: tuple[str, ...]) -> bool:
    root = module.split(".")[0]
    return root in STDLIB_MODULES or any(module == prefix or module.startswith(f"{prefix}.") for prefix in prefixes)


def violations(package: str, forbidden: tuple[str, ...], allowed: tuple[str, ...]) -> list[str]:
    found: list[str] = []
    for source_file in (SOURCE_ROOT / package).rglob("*.py"):
        for module, level in imported_modules(source_file):
            if level != 0:
                continue
            if any(module == prefix or module.startswith(f"{prefix}.") for prefix in forbidden):
                found.append(f"{package}/{source_file.name}: {module}")
            elif not is_stdlib_or(module, allowed):
                found.append(f"{package}/{source_file.name}: unexpected {module}")
    return found


def test_domain_has_no_application_presentation_adapter_or_click_imports() -> None:
    assert (
        violations(
            "domain",
            forbidden=("dm_cli.application", "dm_cli.presentation", "dm_cli.adapters", "click"),
            allowed=("dm_cli.domain", "db_cli_kit", "dm_client.domain"),
        )
        == []
    )


def test_application_has_no_click_presentation_or_adapter_imports() -> None:
    assert (
        violations(
            "application",
            forbidden=("click", "dm_cli.presentation", "dm_cli.adapters"),
            allowed=("dm_cli.domain", "dm_cli.ports", "dm_cli.application", "dm_cli.composition", "db_cli_kit", "dm_client"),
        )
        == []
    )


def test_presentation_has_no_adapter_imports() -> None:
    assert (
        violations(
            "presentation",
            forbidden=("dm_cli.adapters",),
            allowed=("dm_cli", "dm_cli.domain", "dm_cli.application", "dm_cli.ports", "dm_cli.presentation", "db_cli_kit", "dm_client", "click"),
        )
        == []
    )


def test_cli_tree_never_imports_the_dmpython_module() -> None:
    violations_found: list[str] = []
    for source_file in SOURCE_ROOT.rglob("*.py"):
        for module, level in imported_modules(source_file):
            if level == 0 and module.split(".")[0] == DMPYTHON_MODULE:
                violations_found.append(f"{source_file.relative_to(SOURCE_ROOT).as_posix()}: {module}")

    assert violations_found == []


def test_only_composition_imports_the_concrete_dm_client_adapters() -> None:
    importers: list[str] = []
    for source_file in SOURCE_ROOT.rglob("*.py"):
        for module, level in imported_modules(source_file):
            if level != 0:
                continue
            if module == DM_CLIENT_ADAPTERS_MODULE or module.startswith(f"{DM_CLIENT_ADAPTERS_MODULE}."):
                importers.append(source_file.relative_to(SOURCE_ROOT).as_posix())

    assert importers == ["composition.py"]
