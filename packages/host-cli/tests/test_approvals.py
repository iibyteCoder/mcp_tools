"""Approvals are bound to one command, one profile, and one expiry.

An approval that could be reused, transplanted, or kept forever would be a
permanent bypass wearing a token's clothes. These tests pin the three bindings.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from db_cli_kit.profiles import ProfileName
from host_cli.domain.enums import ApprovalState
from host_cli.infrastructure.approvals import check, digest, issue, read

if TYPE_CHECKING:
    from pathlib import Path

PROFILE = ProfileName(value="dev")
OTHER = ProfileName(value="prod")
COMMAND = "systemctl restart nginx"


def test_a_fresh_approval_authorises_its_command(tmp_path: Path) -> None:
    path = tmp_path / "approvals.json"
    approval = issue(path=path, profile=PROFILE, command=COMMAND)

    assert check(path=path, profile=PROFILE, command=COMMAND, token=approval.token) is ApprovalState.GRANTED


def test_an_approval_does_not_authorise_a_different_command(tmp_path: Path) -> None:
    """The token is bound to a digest, so it cannot be aimed at something else."""

    path = tmp_path / "approvals.json"
    approval = issue(path=path, profile=PROFILE, command=COMMAND)

    state = check(path=path, profile=PROFILE, command="rm -rf /", token=approval.token)

    assert state is ApprovalState.MISMATCH


def test_an_approval_does_not_authorise_a_different_profile(tmp_path: Path) -> None:
    path = tmp_path / "approvals.json"
    approval = issue(path=path, profile=PROFILE, command=COMMAND)

    state = check(path=path, profile=OTHER, command=COMMAND, token=approval.token)

    assert state is ApprovalState.REQUIRED


def test_an_expired_approval_is_reported_as_expired(tmp_path: Path) -> None:
    path = tmp_path / "approvals.json"
    approval = issue(path=path, profile=PROFILE, command=COMMAND, ttl_seconds=-1)

    state = check(path=path, profile=PROFILE, command=COMMAND, token=approval.token)

    assert state is ApprovalState.EXPIRED


def test_no_approval_at_all_is_reported_as_required(tmp_path: Path) -> None:
    path = tmp_path / "approvals.json"

    assert check(path=path, profile=PROFILE, command=COMMAND, token="deadbeef") is ApprovalState.REQUIRED


def test_the_command_itself_is_never_stored(tmp_path: Path) -> None:
    """An approval record must not become a log of what was about to run."""

    path = tmp_path / "approvals.json"
    issue(path=path, profile=PROFILE, command=COMMAND)

    assert COMMAND not in path.read_text(encoding="utf-8")


def test_the_digest_is_stable_for_the_same_command() -> None:
    assert digest(COMMAND) == digest(COMMAND)


def test_different_commands_have_different_digests() -> None:
    assert digest(COMMAND) != digest("systemctl restart other")


def test_issuing_prunes_expired_approvals(tmp_path: Path) -> None:
    path = tmp_path / "approvals.json"
    issue(path=path, profile=PROFILE, command=COMMAND, ttl_seconds=-1)
    issue(path=path, profile=PROFILE, command="ps aux")

    assert len(read(path)) == 1


def test_a_corrupt_file_yields_no_approvals(tmp_path: Path) -> None:
    """An unreadable file must mean "no approval", never "approved"."""

    path = tmp_path / "approvals.json"
    path.write_text("{not json", encoding="utf-8")

    assert read(path) == ()
    assert check(path=path, profile=PROFILE, command=COMMAND, token="x") is ApprovalState.REQUIRED


def test_an_approval_survives_a_reload(tmp_path: Path) -> None:
    path = tmp_path / "approvals.json"
    approval = issue(path=path, profile=PROFILE, command=COMMAND)

    stored = read(path)

    assert len(stored) == 1
    assert stored[0].token == approval.token
    assert stored[0].command_digest == approval.command_digest


def test_the_expiry_is_in_the_future_for_a_normal_issue(tmp_path: Path) -> None:
    path = tmp_path / "approvals.json"
    approval = issue(path=path, profile=PROFILE, command=COMMAND)

    assert approval.expires_at > approval.issued_at
    assert approval.expires_at - approval.issued_at == timedelta(seconds=600)


def test_a_token_is_not_reused_between_issues(tmp_path: Path) -> None:
    path = tmp_path / "approvals.json"
    first = issue(path=path, profile=PROFILE, command=COMMAND)
    second = issue(path=path, profile=PROFILE, command=COMMAND)

    assert first.token != second.token


def test_the_token_comparison_ignores_surrounding_space(tmp_path: Path) -> None:
    path = tmp_path / "approvals.json"
    approval = issue(path=path, profile=PROFILE, command=COMMAND)

    state = check(path=path, profile=PROFILE, command=COMMAND, token=f"  {approval.token}  ")

    assert state is ApprovalState.GRANTED
