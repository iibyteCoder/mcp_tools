"""Parsing a command line into commands, without judging any of them."""

from __future__ import annotations

import pytest

from host_cli.domain.shell_syntax import ShellCommand, parse_commands


def _names(command: str) -> list[str | None]:
    return [parsed.name for parsed in parse_commands(command)]


def test_a_simple_command_yields_its_name_and_arguments() -> None:
    parsed = parse_commands("tail -n 100 /var/log/messages")

    assert len(parsed) == 1
    assert parsed[0].name == "tail"
    assert parsed[0].args == ("-n", "100", "/var/log/messages")
    assert parsed[0].dynamic_name is False


def test_an_absolute_path_reports_the_same_basename() -> None:
    """``/bin/rm`` must look like ``rm`` to the policy, not like a new command."""

    parsed = parse_commands("/bin/rm -rf /")

    assert parsed[0].basename == "rm"


def test_a_pipeline_yields_every_command_in_order() -> None:
    parsed = parse_commands("ps aux | grep nginx")

    assert [item.basename for item in parsed] == ["ps", "grep"]


def test_a_compound_statement_is_descended_into() -> None:
    """A loop body is where the destructive command actually lives."""

    parsed = parse_commands("for d in /tmp/*; do rm -rf $d; done")

    assert any(item.basename == "rm" for item in parsed)


def test_quoting_is_removed_from_argument_text() -> None:
    parsed = parse_commands("""bash -c 'rm -rf /'""")

    assert parsed[0].basename == "bash"
    assert "rm -rf /" in parsed[0].args


def test_arithmetic_expansion_does_not_raise() -> None:
    """``$((...))`` broke the first parser this project tried.

    Recording it here keeps the reason for the current choice visible: an
    incomplete parser reports a syntax error, and a syntax error has to be
    treated as "unknown", which is how a guard quietly stops guarding.
    """

    parsed = parse_commands("echo $((1+2))")

    assert parsed[0].basename == "echo"


def test_a_case_statement_does_not_raise() -> None:
    parsed = parse_commands("case $1 in start) systemctl start x;; esac")

    assert any(item.basename == "systemctl" for item in parsed)


def test_a_here_document_does_not_raise() -> None:
    parsed = parse_commands("cat <<EOF > /tmp/x.conf\nkey=value\nEOF")

    assert parsed[0].basename == "cat"


@pytest.mark.parametrize(
    "command",
    [
        "$(echo rm) -rf /",
        "`echo rm` -rf /",
        "$X -rf /",
    ],
)
def test_a_run_time_command_name_is_marked_dynamic(command: str) -> None:
    """The name does not exist until execution, so it cannot be compared.

    Reporting this honestly is the whole point: a parser that returned the
    literal text ``$(echo rm)`` as a command name would look like a clean result.
    """

    parsed = parse_commands(command)

    assert parsed
    assert parsed[0].dynamic_name is True
    assert parsed[0].name is None


def test_a_literal_command_is_not_marked_dynamic() -> None:
    assert parse_commands("rm -rf /tmp/x")[0].dynamic_name is False


def test_an_empty_command_line_yields_no_commands() -> None:
    assert parse_commands("") == ()


def test_the_result_is_an_immutable_sequence_of_commands() -> None:
    parsed = parse_commands("ls")

    assert isinstance(parsed, tuple)
    assert isinstance(parsed[0], ShellCommand)
