"""A dry run must predict every gate, not just the danger one.

The distinction matters more than it looks: a probe that answered only the danger
question would report green for a command the profile is configured to refuse.
The caller would check first, see green, then be refused -- which is worse than
having no probe, because it teaches the caller to distrust the tool.
"""

from __future__ import annotations

from db_cli_kit.profiles import ProfileName
from host_cli.application.guard import predict
from host_cli.domain.enums import ErrorCode, GuardVerdict
from host_cli.domain.models import ProfileRecord, ProfileSettings

NAME = ProfileName(value="dev")


def record(
    *,
    read_only: bool = False,
    requires_approval: bool = False,
    max_commands_per_minute: int = 0,
) -> ProfileRecord:
    return ProfileRecord(
        name=NAME,
        settings=ProfileSettings(
            host="example",
            user="operator",
            read_only=read_only,
            requires_approval=requires_approval,
            max_commands_per_minute=max_commands_per_minute,
        ),
    )


def test_a_clear_command_on_a_plain_profile_is_predicted_clear() -> None:
    prediction = predict(record=record(), command="ps aux", forced=False)

    assert prediction.would_block is False
    assert prediction.reason is None
    assert prediction.report.verdict is GuardVerdict.CLEAR


def test_a_dangerous_command_names_the_danger_gate() -> None:
    prediction = predict(record=record(), command="rm -rf /", forced=False)

    assert prediction.would_block is True
    assert prediction.reason is ErrorCode.DANGEROUS_COMMAND


def test_forcing_clears_the_danger_prediction() -> None:
    prediction = predict(record=record(), command="rm -rf /", forced=True)

    assert prediction.would_block is False


def test_a_safe_command_on_a_read_only_profile_names_the_read_only_gate() -> None:
    """The case this module exists for.

    ``systemctl restart nginx`` matches no danger rule, so a danger-only probe
    would call it clear. The read-only gate will refuse it, and the probe has to
    say so.
    """

    prediction = predict(record=record(read_only=True), command="systemctl restart nginx", forced=False)

    assert prediction.would_block is True
    assert prediction.reason is ErrorCode.READ_ONLY_VIOLATION


def test_an_inspection_command_on_a_read_only_profile_is_predicted_clear() -> None:
    prediction = predict(record=record(read_only=True), command="docker ps", forced=False)

    assert prediction.would_block is False


def test_forcing_does_not_clear_a_read_only_prediction() -> None:
    """``--force`` is about danger; the prediction must not imply otherwise."""

    prediction = predict(record=record(read_only=True), command="systemctl restart nginx", forced=True)

    assert prediction.reason is ErrorCode.READ_ONLY_VIOLATION


def test_an_approval_gated_profile_names_the_approval_gate() -> None:
    prediction = predict(record=record(requires_approval=True), command="ps aux", forced=False)

    assert prediction.reason is ErrorCode.APPROVAL_REQUIRED


def test_a_probe_never_consumes_a_rate_slot() -> None:
    """A probe that counted would make checking a command cost the allowance."""

    profile = record(max_commands_per_minute=1)

    for _ in range(5):
        assert predict(record=profile, command="ps aux", forced=False).reason is None


def test_an_unresolvable_command_is_still_reported_as_blocked() -> None:
    prediction = predict(record=record(), command="rm -rf $TARGET", forced=False)

    assert prediction.would_block is True
    assert prediction.reason is ErrorCode.DANGEROUS_COMMAND
