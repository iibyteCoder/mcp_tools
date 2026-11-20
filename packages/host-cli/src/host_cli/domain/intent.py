"""Deciding whether a command only reads, for profiles that must not mutate.

Read-only profiles invert the usual question. The danger guard asks "is this
irreversible", which needs a list of destructive shapes; this asks "could this
change anything", which needs a list of safe shapes. Inversion is what makes the
protection strong: an unrecognised command is a mutation, so a new tool or a new
spelling fails closed instead of walking through.

The cost is honest and worth stating: a read-only profile refuses some genuinely
read-only commands that are not on the list. That is the intended trade, and
``profile set --writable`` is the way out when it bites.
"""

from __future__ import annotations

from typing import Final

from host_cli.domain.enums import CommandIntent
from host_cli.domain.shell_syntax import ShellCommand, parse_commands

INSPECTION_COMMANDS: Final[frozenset[str]] = frozenset(
    {
        "awk",
        "cat",
        "column",
        "cut",
        "date",
        "df",
        "diff",
        "dig",
        "dirname",
        "du",
        "echo",
        "egrep",
        "env",
        "fc",
        "fgrep",
        "file",
        "find",
        "free",
        "grep",
        "head",
        "hostid",
        "hostname",
        "id",
        "ifconfig",
        "ip",
        "journalctl",
        "jq",
        "last",
        "ls",
        "lsblk",
        "lscpu",
        "lsof",
        "md5sum",
        "mount",
        "netstat",
        "nproc",
        "pgrep",
        "pidof",
        "printf",
        "ps",
        "pwd",
        "readlink",
        "realpath",
        "route",
        "sed",
        "sha1sum",
        "sha256sum",
        "sort",
        "ss",
        "stat",
        "tac",
        "tail",
        "test",
        "tr",
        "true",
        "uname",
        "uniq",
        "uptime",
        "vmstat",
        "wc",
        "wget",
        "which",
        "who",
        "whoami",
        "xargs",
    }
)
"""Commands whose ordinary use only reads.

``sed`` and ``xargs`` are included with a caveat handled below: both can mutate,
so they are checked for their writing forms rather than trusted outright.

``find`` is included because it is the standard way to locate files; its
``-delete`` and ``-exec`` forms are caught separately.
"""

INSPECTION_SUBCOMMANDS: Final[dict[str, frozenset[str]]] = {
    "systemctl": frozenset(
        {
            "status",
            "show",
            "cat",
            "list-units",
            "list-unit-files",
            "list-timers",
            "list-sockets",
            "list-dependencies",
            "is-active",
            "is-enabled",
            "is-failed",
            "get-default",
        }
    ),
    "service": frozenset({"status"}),
    "docker": frozenset({"ps", "images", "logs", "inspect", "version", "info", "stats"}),
    "docker-compose": frozenset({"ps", "logs", "config"}),
    "podman": frozenset({"ps", "images", "logs", "inspect", "version"}),
    "kubectl": frozenset({"get", "describe", "logs", "version"}),
    "nginx": frozenset({"-t", "-T", "-v", "-V"}),
    "mysql": frozenset({"-e"}),
    "redis-cli": frozenset({"info", "get", "ping"}),
    "git": frozenset({"status", "log", "diff", "show", "branch", "remote"}),
    "rpm": frozenset({"-q", "-qa", "-qi", "--version"}),
    "yum": frozenset({"list", "info", "search"}),
    "apt": frozenset({"list"}),
    "ss": frozenset(),
}
"""Per-command safe subcommands.

A command listed here is refused unless its first argument is one of these, so
``systemctl restart nginx`` fails while ``systemctl status nginx`` passes. The
default is refusal, not permission.
"""

SED_IN_PLACE_FLAGS: Final[frozenset[str]] = frozenset({"-i", "--in-place", "-i.bak"})
"""``sed -i`` rewrites its input file, so it is not an inspection command."""

XARGS_WRITE_FLAGS: Final[frozenset[str]] = frozenset({"-I", "-i"})
"""``xargs`` itself only reads; the command it runs decides, checked separately."""


def classify_intent(command: str) -> CommandIntent:
    """Return whether ``command`` may run against a read-only profile.

    Every command in the line must be an inspection command; one mutation makes
    the whole invocation a mutation, because the shell would run them all.
    """

    parsed = parse_commands(command)
    if not parsed:
        return CommandIntent.MUTATION
    return CommandIntent.MUTATION if any(_is_mutation(item) for item in parsed) else CommandIntent.INSPECTION


def _is_mutation(command: ShellCommand) -> bool:
    """Return whether one parsed command could change the machine."""

    if command.dynamic_name:
        return True
    if _writes_a_file(command):
        return True
    name = command.basename
    if name is None:
        return True
    if name in INSPECTION_COMMANDS:
        return _mutating_form(name, command.args)
    allowed = INSPECTION_SUBCOMMANDS.get(name)
    if allowed is None:
        return True
    return not _matches_subcommand(command.args, allowed)


def _writes_a_file(command: ShellCommand) -> bool:
    """Return whether the command redirects into a real file.

    Writing to ``/dev/null`` is how read-only commands discard noise, so that one
    target is exempt; anything else is a write.
    """

    for redirect in command.redirects:
        if redirect.target is None:
            return True
        if redirect.target.rstrip("/") == "/dev/null":
            continue
        return True
    return False


def _mutating_form(name: str, args: tuple[str, ...]) -> bool:
    """Return whether a normally safe command was given a writing form."""

    if name == "sed":
        return any(arg in SED_IN_PLACE_FLAGS or arg.startswith("--in-place") for arg in args)
    if name == "find":
        return any(arg in {"-delete", "-exec", "-execdir", "-ok"} for arg in args)
    if name == "xargs":
        return any(arg in XARGS_WRITE_FLAGS for arg in args)
    if name == "ip":
        return any(arg in {"add", "del", "delete", "set", "flush", "change"} for arg in args)
    if name == "ifconfig":
        return any(arg in {"up", "down", "add"} for arg in args)
    return False


def _matches_subcommand(args: tuple[str, ...], allowed: frozenset[str]) -> bool:
    """Return whether the first meaningful argument is an allowed subcommand."""

    for arg in args:
        if arg.startswith("-"):
            return arg in allowed
        return arg in allowed
    return False


__all__ = ["INSPECTION_COMMANDS", "INSPECTION_SUBCOMMANDS", "classify_intent"]
