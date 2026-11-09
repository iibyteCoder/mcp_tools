"""Architecture contracts for the typed Redis client boundary."""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

from redis_cli.domain.profiles import RedisConnectionConfig, RedisSettings
from redis_cli.domain.secrets import SecretValue

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src" / "redis_cli"


def imported_modules(source_file: Path) -> list[str]:
    """Return the absolute modules imported by one Python source file."""

    module = ast.parse(source_file.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(module):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            names.append(node.module or "")
    return names


def source_files(*relative_paths: str) -> list[Path]:
    """Expand a mix of source files and directories below the package root."""

    files: list[Path] = []
    for relative_path in relative_paths:
        path = SOURCE_ROOT / relative_path
        files.extend(path.rglob("*.py") if path.is_dir() else [path])
    return files


def redis_driver_importers() -> list[str]:
    """Return every source file that imports the redis-py driver."""

    return sorted(
        {
            source_file.relative_to(SOURCE_ROOT).as_posix()
            for source_file in SOURCE_ROOT.rglob("*.py")
            for module in imported_modules(source_file)
            if module.split(".")[0] == "redis"
        }
    )


def test_domain_application_and_ports_do_not_import_redis() -> None:
    violations = [
        f"{source_file.relative_to(SOURCE_ROOT).as_posix()}: {module}"
        for source_file in source_files("domain", "application.py", "ports")
        for module in imported_modules(source_file)
        if module.split(".")[0] == "redis"
    ]

    assert violations == []


def test_client_module_is_removed_and_not_imported() -> None:
    assert importlib.util.find_spec("redis_cli.client") is None
    assert not (SOURCE_ROOT / "client.py").exists()
    references = [
        source_file.relative_to(SOURCE_ROOT).as_posix()
        for source_file in SOURCE_ROOT.rglob("*.py")
        if "redis_cli.client" in source_file.read_text(encoding="utf-8")
    ]

    assert references == []


def test_only_the_redis_py_adapter_imports_the_redis_driver() -> None:
    assert redis_driver_importers() == ["adapters/redis_py.py"]


def test_domain_package_does_not_reexport_submodule_members() -> None:
    domain = importlib.import_module("redis_cli.domain")
    reexported = [
        name
        for name in ("ProfileRegistry", "RedisConnectionConfig", "RedisCliError", "SecretValue")
        if hasattr(domain, name)
    ]
    package_imports = [
        source_file.relative_to(SOURCE_ROOT).as_posix()
        for source_file in SOURCE_ROOT.rglob("*.py")
        if "from redis_cli.domain import" in source_file.read_text(encoding="utf-8")
    ]

    assert not hasattr(domain, "__all__")
    assert reexported == []
    assert package_imports == []


def test_connection_config_repr_does_not_reveal_the_password() -> None:
    secret = "s3cr3t-connection-password"
    config = RedisConnectionConfig.from_settings(
        RedisSettings(host="127.0.0.1"),
        password=SecretValue(secret),
    )

    assert secret not in repr(config)
    assert secret not in str(config)
    assert secret not in repr(config.password)
