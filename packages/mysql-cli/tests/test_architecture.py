from __future__ import annotations

import ast
import inspect
from pathlib import Path

from mysql_cli.application.runner import execute_request

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PACKAGE_ROOT = REPOSITORY_ROOT / "packages" / "mysql-cli"
SOURCE_ROOTS = (
    REPOSITORY_ROOT / "libs" / "mysql-client" / "src" / "mysql_client",
    PACKAGE_ROOT / "src" / "mysql_cli",
)
SHARED_MODULE = "mysql_cli.shared"
SECRET_STORE_MODULES = frozenset(
    {
        "mysql_cli.adapters.secret_store",
        "mysql_cli.ports.secret_store",
    }
)
KIT_PROFILE_PRIMITIVES = frozenset({"DirectoryBinding", "ProfileName", "normalize_directory"})


def imported_modules(module: ast.Module) -> set[str]:
    """Return every module name imported by one parsed module."""

    imported: set[str] = set()
    for node in ast.walk(module):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    return imported


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


def test_mysql_cli_no_longer_defines_a_local_json_codec() -> None:
    assert not (SOURCE_ROOTS[1] / "shared").exists()
    offenders = [
        source_file.relative_to(REPOSITORY_ROOT)
        for source_file in PACKAGE_ROOT.rglob("*.py")
        if any(
            name == SHARED_MODULE or name.startswith(f"{SHARED_MODULE}.")
            for name in imported_modules(ast.parse(source_file.read_text(encoding="utf-8")))
        )
    ]
    assert offenders == []


def test_secret_store_wrapper_modules_are_removed() -> None:
    removed_modules = (
        PACKAGE_ROOT / "src" / "mysql_cli" / "ports" / "secret_store.py",
        PACKAGE_ROOT / "src" / "mysql_cli" / "adapters" / "secret_store.py",
    )
    assert [path for path in removed_modules if path.exists()] == []
    offenders = [
        source_file.relative_to(REPOSITORY_ROOT)
        for source_file in PACKAGE_ROOT.rglob("*.py")
        if imported_modules(ast.parse(source_file.read_text(encoding="utf-8"))) & SECRET_STORE_MODULES
    ]
    assert offenders == []


def test_domain_profile_does_not_reexport_kit_profile_primitives() -> None:
    source_file = SOURCE_ROOTS[1] / "domain" / "profile.py"
    module = ast.parse(source_file.read_text(encoding="utf-8"))
    exported: set[str] = set()
    for node in module.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets):
            continue
        exported = set(ast.literal_eval(node.value))

    assert exported.isdisjoint(KIT_PROFILE_PRIMITIVES)


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
