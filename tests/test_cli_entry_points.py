"""Every console entry point must make the process speak UTF-8.

This is an architecture test, not a behaviour test: it reads each declared
console script, walks to the ``main`` it names, and asserts the very first
statement reconfigures the standard streams. A new CLI that forgets the call
fails here rather than shipping mangled output on a non-UTF-8 host.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
import tomllib

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
ENFORCER_NAME = "enforce_utf8_stdio"
PACKAGE_GLOB = "packages/*/pyproject.toml"


def _console_scripts() -> list[tuple[str, str, Path]]:
    """Return ``(package, script, source path)`` for every declared entry point."""

    entries: list[tuple[str, str, Path]] = []
    for manifest_path in sorted(WORKSPACE_ROOT.glob(PACKAGE_GLOB)):
        manifest = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
        scripts = manifest.get("project", {}).get("scripts", {})
        package = manifest_path.parent
        for script, target in sorted(scripts.items()):
            module_path, _, function = target.partition(":")
            source = package / "src" / Path(*module_path.split(".")).with_suffix(".py")
            entries.append((script, function, source))
    return entries


def test_at_least_one_console_script_is_declared() -> None:
    assert _console_scripts(), "no console scripts found; the glob or layout changed"


@pytest.mark.parametrize(
    ("script", "function", "source"),
    _console_scripts(),
    ids=lambda value: value if isinstance(value, str) else "",
)
def test_entry_point_calls_enforce_utf8_stdio_first(script: str, function: str, source: Path) -> None:
    assert source.is_file(), f"{script}: {source} does not exist"
    tree = ast.parse(source.read_text(encoding="utf-8"))

    main_function = _find_function(tree, function)
    first_statement = _first_statement(main_function)
    called = _first_called_name(first_statement)

    assert called == ENFORCER_NAME, (
        f"{script}: `{function}` must start with {ENFORCER_NAME}(), found {called!r}. "
        "Without it the CLI inherits the host code page and mangles non-ASCII output."
    )


def _find_function(tree: ast.Module, name: str) -> ast.FunctionDef:
    """Return the named function definition from a module."""

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"function {name!r} not found")


def _first_statement(function: ast.FunctionDef) -> ast.stmt:
    """Return the first executable statement, skipping a docstring."""

    body = function.body
    if not body:
        raise AssertionError(f"function {function.name!r} has no body")
    is_docstring = (
        isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    )
    if is_docstring and len(body) > 1:
        return body[1]
    return body[0]


def _first_called_name(statement: ast.stmt) -> str | None:
    """Return the name called by a bare ``name(...)`` statement."""

    if not isinstance(statement, ast.Expr) or not isinstance(statement.value, ast.Call):
        return None
    call = statement.value
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None
