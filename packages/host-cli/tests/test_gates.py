"""The three gates composed: danger, read-only, approval, rate.

Each gate is unit-tested on its own; this module tests the composition, because
the order matters and the interactions are where a bypass would hide. A command
refused by the danger guard must never consume a rate slot, and a read-only
profile must not be talked past by an approval token.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from db_cli_kit.profiles import ProfileName
from host_cli.application.guard import gate
from host_cli.domain.enums import ApprovalState, ErrorCode
from host_cli.domain.errors import HostCliError
from host_cli.domain.models import ProfileRecord, ProfileSettings
from host_cli.infrastructure.approvals import issue
from host_cli.infrastructure.rate_limit import remaining

if TYPE_CHECKING:
    from pathlib import Path

NAME = ProfileName(value="dev")
HOST = "example"
USER = "operator"


def record(
    *,
    read_only: bool = False,
    max_commands_per_minute: int = 0,
    requires_approval: bool = False,
    command_timeout: float = 60.0,
) -> ProfileRecord:
    """Build one profile record with the gates configured as asked."""

    return ProfileRecord(
        name=NAME,
        settings=ProfileSettings(
            host=HOST,
            user=USER,
            read_only=read_only,
            max_commands_per_minute=max_commands_per_minute,
            requires_approval=requires_approval,
            command_timeout=command_timeout,
        ),
    )


def apply(
    tmp_path: Path,
    *,
    command: str,
    profile: ProfileRecord | None = None,
    forced: bool = False,
    token: str | None = None,
) -> None:
    """Run the composed gate against temporary storage."""

    gate(
        record=profile or record(),
        command=command,
        forced=forced,
        approval_token=token,
        approvals_path=tmp_path / "approvals.json",
        rate_path=tmp_path / "rate.json",
    )


def error_of(tmp_path: Path, **arguments: object) -> HostCliError:
    """Run the gate and return the failure it raised."""

    with pytest.raises(HostCliError) as raised:
        apply(tmp_path, **arguments)  # type: ignore[arg-type]
    return raised.value


def test_a_clean_command_passes_every_gate(tmp_path: Path) -> None:
    apply(tmp_path, command="ps aux")


def test_a_dangerous_command_is_refused_by_the_first_gate(tmp_path: Path) -> None:
    assert error_of(tmp_path, command="rm -rf /").code is ErrorCode.DANGEROUS_COMMAND


def test_forcing_clears_the_danger_gate(tmp_path: Path) -> None:
    apply(tmp_path, command="rm -rf /", forced=True)


def test_a_read_only_profile_refuses_a_mutation(tmp_path: Path) -> None:
    profile = record(read_only=True)

    failure = error_of(tmp_path, command="systemctl restart nginx", profile=profile)

    assert failure.code is ErrorCode.READ_ONLY_VIOLATION


def test_a_read_only_profile_allows_inspection(tmp_path: Path) -> None:
    apply(tmp_path, command="systemctl status nginx", profile=record(read_only=True))


def test_forcing_does_not_clear_the_read_only_gate(tmp_path: Path) -> None:
    """``--force`` is about danger, not about intent. Read-only has no override.

    If forcing could mark a profile writable for one call, the mode would be
    advisory rather than a guarantee, and an agent would discover ``--force`` the
    same way it discovers everything else.
    """

    profile = record(read_only=True)

    failure = error_of(tmp_path, command="systemctl restart nginx", profile=profile, forced=True)

    assert failure.code is ErrorCode.READ_ONLY_VIOLATION


def test_an_approval_does_not_clear_the_read_only_gate(tmp_path: Path) -> None:
    profile = record(read_only=True)
    approval = issue(path=tmp_path / "approvals.json", profile=NAME, command="systemctl restart nginx")

    failure = error_of(
        tmp_path,
        command="systemctl restart nginx",
        profile=profile,
        token=approval.token,
    )

    assert failure.code is ErrorCode.READ_ONLY_VIOLATION


def test_a_profile_needing_approval_refuses_without_a_token(tmp_path: Path) -> None:
    profile = record(requires_approval=True)

    failure = error_of(tmp_path, command="ps aux", profile=profile)

    assert failure.code is ErrorCode.APPROVAL_REQUIRED


def test_a_matching_approval_lets_the_command_through(tmp_path: Path) -> None:
    profile = record(requires_approval=True)
    approval = issue(path=tmp_path / "approvals.json", profile=NAME, command="ps aux")

    apply(tmp_path, command="ps aux", profile=profile, token=approval.token)


def test_an_approval_for_another_command_is_refused(tmp_path: Path) -> None:
    profile = record(requires_approval=True)
    approval = issue(path=tmp_path / "approvals.json", profile=NAME, command="ps aux")

    failure = error_of(tmp_path, command="df -h", profile=profile, token=approval.token)

    assert failure.code is ErrorCode.APPROVAL_REQUIRED
    assert "different command" in failure.message


def test_an_expired_approval_is_refused(tmp_path: Path) -> None:
    profile = record(requires_approval=True)
    approval = issue(path=tmp_path / "approvals.json", profile=NAME, command="ps aux", ttl_seconds=-1)

    failure = error_of(tmp_path, command="ps aux", profile=profile, token=approval.token)

    assert "expired" in failure.message


def test_the_rate_ceiling_refuses_the_call_after_the_limit(tmp_path: Path) -> None:
    profile = record(max_commands_per_minute=2)
    apply(tmp_path, command="ps aux", profile=profile)
    apply(tmp_path, command="ps aux", profile=profile)

    failure = error_of(tmp_path, command="ps aux", profile=profile)

    assert failure.code is ErrorCode.RATE_LIMITED


def test_a_dangerous_command_does_not_consume_a_rate_slot(tmp_path: Path) -> None:
    """A command that could never run must not count against the allowance."""

    profile = record(max_commands_per_minute=1)
    with pytest.raises(HostCliError):
        apply(tmp_path, command="rm -rf /", profile=profile)

    assert remaining(path=tmp_path / "rate.json", profile=NAME, limit=1) == 1


def test_a_read_only_refusal_does_not_consume_a_rate_slot(tmp_path: Path) -> None:
    profile = record(read_only=True, max_commands_per_minute=1)
    with pytest.raises(HostCliError):
        apply(tmp_path, command="systemctl restart nginx", profile=profile)

    assert remaining(path=tmp_path / "rate.json", profile=NAME, limit=1) == 1


def test_a_missing_approval_does_not_consume_a_rate_slot(tmp_path: Path) -> None:
    profile = record(requires_approval=True, max_commands_per_minute=1)
    with pytest.raises(HostCliError):
        apply(tmp_path, command="ps aux", profile=profile)

    assert remaining(path=tmp_path / "rate.json", profile=NAME, limit=1) == 1


def test_all_three_gates_apply_at_once(tmp_path: Path) -> None:
    """A profile can be read-only, approval-gated and rate-limited together."""

    profile = record(read_only=True, requires_approval=True, max_commands_per_minute=5)

    with pytest.raises(HostCliError) as raised:
        apply(tmp_path, command="systemctl restart nginx", profile=profile)
    assert raised.value.code is ErrorCode.READ_ONLY_VIOLATION

    approval = issue(path=tmp_path / "approvals.json", profile=NAME, command="ps aux")
    apply(tmp_path, command="ps aux", profile=profile, token=approval.token)


def test_an_approval_state_names_the_remedy(tmp_path: Path) -> None:
    """A caller reading the message must know what to do next, not just that it failed."""

    profile = record(requires_approval=True)

    failure = error_of(tmp_path, command="ps aux", profile=profile)

    assert ApprovalState.REQUIRED.value in failure.code.value or "approval" in failure.message
