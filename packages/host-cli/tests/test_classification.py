"""Classification is the part that must never guess silently."""

from __future__ import annotations

import pytest
from conftest import execution

from host_cli.domain.classification import classify
from host_cli.domain.enums import EvidenceStrength, HostKeyProblem, OutcomeKind

HOST_KEY_FINGERPRINT = "ssh-ed25519 SHA256:nyxtCG7FINi+L59fz1YvNwl4cdHOYzqRU5u4hX9L400"

AUTHENTICATED = f'debug1: Authenticated to 10.0.0.1 ([10.0.0.1]:22) using "password".\ndebug1: Server host key: {HOST_KEY_FINGERPRINT}\n'
TRANSPORT_REFUSED = 'debug2: resolving "example" port 22\nssh: connect to host example port 22: Connection refused\n'
EXIT_ZERO = "debug1: Exit status 0\n"
EXIT_SEVEN = "debug1: Exit status 7\n"
EXIT_255 = "debug1: Exit status 255\n"
EXIT_SIGNAL = "debug1: client_input_channel_req: channel 0 rtype exit-signal reply 0\ndebug1: Exit status -1\n"


def _log(*parts: str) -> str:
    return "".join(parts)


def test_a_relayed_zero_status_is_success() -> None:
    outcome = classify(execution(exit_code=0, debug_log=_log(AUTHENTICATED, EXIT_ZERO)))

    assert outcome.kind is OutcomeKind.SUCCESS
    assert outcome.evidence is EvidenceStrength.DECISIVE


@pytest.mark.parametrize("status", [1, 7, 42, 127, 200, 254])
def test_relayed_non_zero_statuses_are_preserved(status: int) -> None:
    outcome = classify(execution(exit_code=status, debug_log=_log(AUTHENTICATED, f"debug1: Exit status {status}\n")))

    assert outcome.kind is OutcomeKind.REMOTE_NONZERO_EXIT


def test_remote_255_is_distinguished_from_transport_255() -> None:
    outcome = classify(execution(exit_code=255, debug_log=_log(AUTHENTICATED, EXIT_255)))

    assert outcome.kind is OutcomeKind.REMOTE_NONZERO_EXIT


def test_transport_255_with_a_refusal_is_a_connection_failure() -> None:
    outcome = classify(execution(exit_code=255, debug_log=TRANSPORT_REFUSED))

    assert outcome.kind is OutcomeKind.CONNECTION_FAILED
    assert outcome.evidence is EvidenceStrength.DECISIVE


def test_transport_255_without_any_evidence_is_labelled_a_fallback() -> None:
    outcome = classify(execution(exit_code=255, debug_log=""))

    assert outcome.kind is OutcomeKind.CONNECTION_FAILED
    assert outcome.evidence is EvidenceStrength.FALLBACK


def test_a_relayed_exit_signal_is_a_signal_kill() -> None:
    outcome = classify(execution(exit_code=-1, debug_log=_log(AUTHENTICATED, EXIT_SIGNAL)))

    assert outcome.kind is OutcomeKind.REMOTE_KILLED_BY_SIGNAL


def test_a_broken_pipe_note_does_not_override_a_relayed_status() -> None:
    log = _log(
        AUTHENTICATED,
        "debug2: channel 0: read failed rfd 5 maxlen 32768: Broken pipe\n",
        EXIT_ZERO,
    )

    outcome = classify(execution(exit_code=0, debug_log=log))

    assert outcome.kind is OutcomeKind.SUCCESS


def test_host_key_change_outranks_every_other_signal() -> None:
    log = _log(
        "debug1: Server host key: ssh-ed25519 SHA256:AAA\n",
        "@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@\n",
        "@    WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!     @\n",
        "@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@\n",
        "Host key verification failed.\n",
        "root@10.0.0.1: Permission denied (publickey,password).\n",
    )

    outcome = classify(execution(exit_code=255, debug_log=log))

    assert outcome.kind is OutcomeKind.HOST_KEY_UNTRUSTED
    assert outcome.host_key_problem is HostKeyProblem.CHANGED


def test_unknown_host_key_is_distinguished_from_a_change() -> None:
    log = "No ED25519 host key is known for 10.0.0.1 and you have requested strict checking.\nHost key verification failed.\n"

    outcome = classify(execution(exit_code=255, debug_log=log))

    assert outcome.kind is OutcomeKind.HOST_KEY_UNTRUSTED
    assert outcome.host_key_problem is HostKeyProblem.UNKNOWN


def test_permission_denied_is_an_authentication_failure() -> None:
    log = _log(
        "debug1: Next authentication method: password\n",
        "root@10.0.0.1: Permission denied (publickey,password).\n",
    )

    outcome = classify(execution(exit_code=255, debug_log=log))

    assert outcome.kind is OutcomeKind.AUTHENTICATION_FAILED


@pytest.mark.parametrize(
    "line",
    [
        "ssh: Could not resolve hostname example.invalid: No such file or directory\n",
        "ssh: connect to host 10.0.0.1 port 22: Connection refused\n",
        "ssh: connect to host 10.0.0.1 port 22: Connection timed out\n",
        "kex_exchange_identification: Connection closed by remote host\n",
        "Connection reset by peer\n",
    ],
)
def test_transport_complaints_are_connection_failures(line: str) -> None:
    outcome = classify(execution(exit_code=255, debug_log=line))

    assert outcome.kind is OutcomeKind.CONNECTION_FAILED


def test_a_remote_command_printing_permission_denied_is_not_misread() -> None:
    outcome = classify(
        execution(
            exit_code=1,
            stderr=b"bash: Permission denied\n",
            debug_log=_log(AUTHENTICATED, "debug1: Exit status 1\n"),
        )
    )

    assert outcome.kind is OutcomeKind.REMOTE_NONZERO_EXIT


def test_our_own_timeout_wins_over_every_relayed_status() -> None:
    outcome = classify(execution(exit_code=0, timed_out=True, debug_log=_log(AUTHENTICATED, EXIT_ZERO)))

    assert outcome.kind is OutcomeKind.TIMEOUT


def test_a_missing_ssh_client_is_reported_separately() -> None:
    outcome = classify(execution(spawn_failed=True))

    assert outcome.kind is OutcomeKind.SSH_CLIENT_UNAVAILABLE


def test_reaching_the_host_is_not_claimed_for_a_connection_failure() -> None:
    outcome = classify(execution(exit_code=255, debug_log=TRANSPORT_REFUSED))

    assert not outcome.kind.remote_ran
