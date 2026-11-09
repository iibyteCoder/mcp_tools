"""Architecture tests for the dm-client dependency edges."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import dm_client.ports as ports_package
import dm_client.ports.driver as driver_port
from dm_client.execution.executor import DriverExecutor

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SOURCE_ROOT = REPOSITORY_ROOT / "libs" / "dm-client" / "src" / "dm_client"
STDLIB_MODULES = frozenset(sys.stdlib_module_names)
FORBIDDEN_ROOTS = {"click", "dm_cli", "dmPython"}
FORBIDDEN_MODULE_PREFIXES = ("dm_client.adapters",)
ADAPTER_PACKAGE = (SOURCE_ROOT / "adapters").resolve()
DMPYTHON_PACKAGE = (SOURCE_ROOT / "adapters" / "dmpython").resolve()


def imported_modules(source_file: Path) -> list[tuple[str, int]]:
    """Return absolute imported module names and their relative levels."""

    module = ast.parse(source_file.read_text(encoding="utf-8"))
    imports: list[tuple[str, int]] = []
    for node in ast.walk(module):
        if isinstance(node, ast.Import):
            imports.extend((alias.name, 0) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append((node.module or "", node.level))
    return imports


def is_allowed(module: str, allowed_prefixes: tuple[str, ...]) -> bool:
    root = module.split(".")[0]
    return root in STDLIB_MODULES or any(module == prefix or module.startswith(f"{prefix}.") for prefix in allowed_prefixes)


def test_domain_imports_only_stdlib_and_domain() -> None:
    violations: list[str] = []
    for source_file in (SOURCE_ROOT / "domain").rglob("*.py"):
        for module, level in imported_modules(source_file):
            if level == 0 and not is_allowed(module, ("dm_client.domain",)):
                violations.append(f"{source_file.name}: {module}")

    assert violations == []


def test_ports_import_only_stdlib_and_domain_or_ports() -> None:
    violations: list[str] = []
    for source_file in (SOURCE_ROOT / "ports").rglob("*.py"):
        for module, level in imported_modules(source_file):
            if level == 0 and not is_allowed(module, ("dm_client.domain", "dm_client.ports")):
                violations.append(f"{source_file.name}: {module}")

    assert violations == []


def test_domain_ports_and_execution_do_not_import_adapters_or_driver() -> None:
    violations: list[str] = []
    for package in ("domain", "ports", "execution"):
        for source_file in (SOURCE_ROOT / package).rglob("*.py"):
            for module, level in imported_modules(source_file):
                if level != 0:
                    continue
                root = module.split(".")[0]
                if root in FORBIDDEN_ROOTS or module.startswith(FORBIDDEN_MODULE_PREFIXES):
                    violations.append(f"{source_file.relative_to(SOURCE_ROOT)}: {module}")

    assert violations == []


def test_dmpython_is_imported_only_inside_the_adapter_package() -> None:
    violations: list[str] = []
    for source_file in SOURCE_ROOT.rglob("*.py"):
        for module, level in imported_modules(source_file):
            if level != 0 or module.split(".")[0] != "dmPython":
                continue
            if DMPYTHON_PACKAGE not in source_file.resolve().parents:
                violations.append(str(source_file.relative_to(SOURCE_ROOT)))

    assert violations == []


def test_adapter_package_and_driver_package_exist() -> None:
    assert ADAPTER_PACKAGE.is_dir()
    assert DMPYTHON_PACKAGE.is_dir()


def test_ports_driver_does_not_expose_driver_executor() -> None:
    assert not hasattr(driver_port, "DriverExecutor")
    assert not hasattr(driver_port, "EXECUTOR_THREAD_NAME_PREFIX")
    assert not hasattr(ports_package, "DriverExecutor")
    assert not hasattr(ports_package, "EXECUTOR_THREAD_NAME_PREFIX")


def test_driver_executor_has_one_implementation_in_execution() -> None:
    definitions: list[tuple[str, ...]] = []
    for source_file in SOURCE_ROOT.rglob("*.py"):
        module = ast.parse(source_file.read_text(encoding="utf-8"))
        if any(
            isinstance(node, ast.ClassDef) and node.name == "DriverExecutor"
            for node in ast.walk(module)
        ):
            definitions.append(source_file.relative_to(SOURCE_ROOT).parts)

    assert definitions == [("execution", "executor.py")]
    assert DriverExecutor.__module__ == "dm_client.execution.executor"
    assert not (DMPYTHON_PACKAGE / "executor.py").exists()
