from __future__ import annotations

import json
import os
import runpy
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

MYSQL_CONFIG = cast("dict[str, Any]", runpy.run_path(Path.cwd() / "tests" / "conftest.py")["MYSQL_CONFIG"])


def _resolve_cli() -> list[str]:
    installed = shutil.which("db-mysql")
    if installed:
        return [installed]
    if os.getenv("DB_CLI_FORCE_INSTALLED") == "1":
        raise RuntimeError("db-mysql is not installed")
    return [sys.executable, "-m", "mysql_cli"]


def test_installed_help() -> None:
    result = subprocess.run([*_resolve_cli(), "--help"], capture_output=True, text=True, timeout=10, check=False)

    assert result.returncode == 0
    assert "Commands:" in result.stdout


def test_real_mysql_switch_and_select(tmp_path) -> None:
    environment = os.environ.copy()
    environment.update(
        {
            "MYSQL_HOST": str(MYSQL_CONFIG["host"]),
            "MYSQL_PORT": str(MYSQL_CONFIG["port"]),
            "MYSQL_USER": str(MYSQL_CONFIG["user"]),
            "MYSQL_PASSWORD": str(MYSQL_CONFIG["password"]),
            "MYSQL_DATABASE": str(MYSQL_CONFIG["database"]),
        }
    )
    switch_result = subprocess.run(
        [*_resolve_cli(), "--connection-timeout", "3", "--json", "use", str(MYSQL_CONFIG["database"])],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
        env=environment,
    )
    path = tmp_path / "query.sql"
    path.write_text("SELECT 1 AS ok", encoding="utf-8")
    result = subprocess.run(
        [*_resolve_cli(), "--connection-timeout", "3", "--json", "sql", "query", "--query-file", str(path)],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
        env=environment,
    )

    assert switch_result.returncode == 0, switch_result.stdout + switch_result.stderr
    assert json.loads(switch_result.stdout)["status"] == "success"
    assert json.loads(switch_result.stdout)["profile"] is None
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["data"]["rows"] == [{"ok": 1}]
