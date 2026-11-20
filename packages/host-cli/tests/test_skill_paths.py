"""Skill path resolution must match where the agent runtimes actually look.

The skill ships in this repository but is read from each runtime's installation
root, so the resolver is the only thing that knows both destinations. A wrong path
here means the skill is silently never found.
"""

from __future__ import annotations

from pathlib import Path

from host_cli.skill_paths import (
    AgentHomeDirectory,
    CodexEnvironmentVariable,
    SkillRelativePath,
    resolve_codex_home,
    resolve_dsh_home,
    resolve_host_cli_skill_paths,
)

HOME = Path("/home/operator")


def test_codex_home_defaults_under_the_user_home() -> None:
    resolved = resolve_codex_home(environment={}, user_home=HOME)

    assert resolved == HOME / AgentHomeDirectory.CODEX.value


def test_codex_home_honours_the_environment_variable() -> None:
    resolved = resolve_codex_home(
        environment={CodexEnvironmentVariable.CODEX_HOME.value: "/opt/codex"},
        user_home=HOME,
    )

    assert resolved == Path("/opt/codex")


def test_an_empty_environment_variable_falls_back_to_the_default() -> None:
    """An empty string is not a configured home, and must not become the root."""

    resolved = resolve_codex_home(
        environment={CodexEnvironmentVariable.CODEX_HOME.value: ""},
        user_home=HOME,
    )

    assert resolved == HOME / AgentHomeDirectory.CODEX.value


def test_dsh_home_defaults_under_the_user_home() -> None:
    assert resolve_dsh_home(HOME) == HOME / AgentHomeDirectory.DSH.value


def test_both_targets_point_at_the_host_cli_skill() -> None:
    paths = resolve_host_cli_skill_paths(environment={}, user_home=HOME)

    assert paths.codex.name == "SKILL.md"
    assert paths.dsh.name == "SKILL.md"
    assert paths.codex.parent.name == "host-cli"
    assert paths.dsh.parent.name == "host-cli"


def test_the_two_runtimes_resolve_to_different_roots() -> None:
    """Codex and DSH use separate installation roots; one path cannot serve both."""

    paths = resolve_host_cli_skill_paths(environment={}, user_home=HOME)

    assert paths.codex != paths.dsh


def test_the_relative_path_names_the_repository_layout() -> None:
    """The value must match where the file actually lives in this repo."""

    assert SkillRelativePath.HOST_CLI.value == "skills/host-cli/SKILL.md"


def test_the_skill_document_exists_in_the_repository() -> None:
    """A resolver that points at a file nobody wrote would still pass every test above."""

    repository_root = Path(__file__).resolve().parents[3]

    assert (repository_root / SkillRelativePath.HOST_CLI.value).is_file()
