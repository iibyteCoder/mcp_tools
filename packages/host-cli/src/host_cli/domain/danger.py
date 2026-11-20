"""Detection of irreversible or self-destructive remote commands.

This guard exists because the tool hands an autonomous caller a real shell on a
real machine. It cannot authorise anything -- a determined caller can always
rephrase a command -- so its purpose is narrower and it is built for exactly
that: recognise the classes of command whose consequence cannot be undone, report
which class matched and which words matched it, and require `--force` before the
command leaves the machine.

Detection works on a parsed command line rather than on text, for one reason:
``/bin/rm -rf /``, ``busybox rm -rf /`` and ``sudo -u root /usr/bin/rm -fr /etc``
are the same act written three ways, and no pattern over spelling catches all of
them. The parser lives in ``shell_syntax``; this module holds only the policy.

**Known limit, deliberately not papered over:** a command whose name or target is
produced at run time (``$X``, ``$(cmd)``, ``eval``, ``base64 | sh``) cannot be
resolved statically. When such a value sits in a dangerous position the finding is
reported as ``UNRESOLVED`` and still requires ``--force``. The trade is deliberate:
``rm -rf $BUILD_DIR`` becomes a false positive, because the alternative is letting
``rm -rf $TARGET`` through whenever the variable is spelled differently.
"""

from __future__ import annotations

import posixpath
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from host_cli.domain.enums import DangerCategory
from host_cli.domain.shell_syntax import ShellCommand, parse_commands

if TYPE_CHECKING:
    from collections.abc import Callable

    Detector = Callable[[str, "tuple[str, ...]"], DangerCategory | None]
    """Signature of one policy rule: command name plus arguments to a verdict."""

SYSTEM_ROOTS: Final[frozenset[str]] = frozenset(
    {
        "/",
        "/bin",
        "/boot",
        "/dev",
        "/etc",
        "/home",
        "/lib",
        "/lib64",
        "/opt",
        "/proc",
        "/root",
        "/sbin",
        "/srv",
        "/sys",
        "/usr",
        "/var",
    }
)
"""Trees whose removal, truncation or opening cannot be repaired from the host.

``/tmp`` is deliberately absent: clearing it is routine, and flagging it would
train the caller to pass ``--force`` reflexively, which destroys the signal.
"""

WHOLE_TREE_TARGETS: Final[frozenset[str]] = frozenset({"/", "/*", "~", "~/", "~/*", "$HOME", "*"})
"""Targets meaning "everything here" rather than "one file"."""

WRAPPER_COMMANDS: Final[frozenset[str]] = frozenset(
    {
        "sudo",
        "doas",
        "env",
        "nohup",
        "setsid",
        "nice",
        "time",
        "exec",
        "timeout",
        "chroot",
        "xargs",
        "busybox",
        "stdbuf",
        "ionice",
    }
)
"""Commands that run another command, so the real one is further along.

``xargs`` and ``busybox`` matter as much as ``sudo``: ``echo x | xargs rm -rf``
and ``busybox rm -rf /`` reach the same binary without naming it first.
"""

WRAPPER_OPTIONS_WITH_VALUE: Final[frozenset[str]] = frozenset(
    {
        "-u",
        "-g",
        "-p",
        "-C",
        "-h",
        "-U",
        "-r",
        "-t",
        "-n",
        "-s",
        "-a",
        "-c",
        "-e",
        "-i",
        "-o",
        "-k",
        "-D",
    }
)
"""Wrapper options that consume the next token.

``sudo -u root rm -rf /`` puts ``root`` where a naive scan expects the command,
so the option's value must be skipped rather than mistaken for the target.
``timeout 30 rm -rf /etc`` has no option at all: the bare duration occupies that
slot, which is why ``_first_operand`` also skips a leading plain number.
"""

SHELL_COMMANDS: Final[frozenset[str]] = frozenset({"sh", "bash", "zsh", "dash", "ksh"})
SHELL_COMMAND_FLAG: Final[str] = "-c"

MAX_UNWRAP_DEPTH: Final[int] = 6
"""Bound for nested wrappers, so ``sudo sudo sudo ...`` cannot loop forever."""

RECURSIVE_FLAGS: Final[frozenset[str]] = frozenset({"-r", "-R", "--recursive"})
FORCE_FLAGS: Final[frozenset[str]] = frozenset({"-f", "--force"})
FLUSH_FLAGS: Final[frozenset[str]] = frozenset({"-F", "--flush"})
WORLD_WRITABLE_MODES: Final[frozenset[str]] = frozenset(
    {"777", "0777", "666", "0666", "a+rwx", "o+w", "a+w", "+rwx", "ugo+rwx"}
)
POWER_COMMANDS: Final[frozenset[str]] = frozenset({"shutdown", "reboot", "halt", "poweroff"})

SERVICE_UNITS: Final[frozenset[str]] = frozenset({"sshd", "sshd.service", "firewalld", "firewalld.service"})
"""Units whose absence or stoppage removes the way back in.

``restart`` is deliberately absent from the verbs below: restarting sshd is
routine operation, and flagging it would train the operator to pass ``--force``
without reading. Only ``stop``/``disable``/``mask`` remove access.
"""

ACCESS_REMOVING_VERBS: Final[frozenset[str]] = frozenset({"stop", "disable", "mask"})

NETWORK_INTERFACES_HINT: Final[frozenset[str]] = frozenset({"eth0", "eth1", "ens160", "enp0s3"})
"""Representative names, only used to describe the pattern; matching is textual."""

DANGEROUS_DOCKER_VERBS: Final[frozenset[str]] = frozenset({"prune"})
MASS_DELETE_FLAGS: Final[frozenset[str]] = frozenset({"--delete", "--volumes", "-af", "-fa"})
DESTRUCTIVE_COMMANDS: Final[frozenset[str]] = frozenset({"rm", "find", "mv", "truncate", "shred"})
"""Commands whose effect on a system tree is equivalent to deletion.

``mv /etc /etc.bak`` removes ``/etc`` as thoroughly as ``rm`` would, and
``truncate -s0 /etc/passwd`` empties it while keeping the file present.
"""

IDENTITY_COMMANDS: Final[frozenset[str]] = frozenset({"userdel", "deluser"})
"""Commands that remove a login account, optionally with its home directory."""

PROTECTED_HOME_ROOTS: Final[frozenset[str]] = frozenset({"/root", "/home"})
"""Home trees holding credentials and `authorized_keys` files."""

SAFE_REDIRECT_TARGETS: Final[frozenset[str]] = frozenset(
    {
        "/dev/null",
        "/dev/zero",
        "/dev/stdout",
        "/dev/stderr",
        "/dev/tty",
        "/dev/random",
        "/dev/urandom",
    }
)
"""Device files a redirect may write to harmlessly.

They sit under ``/dev``, which is a protected tree because ``> /dev/sda`` would
destroy a disk, so the exemptions have to be named. ``ls > /dev/null`` is the most
common redirect there is; flagging it would make the guard unusable.
"""

LOG_TREE: Final[str] = "/var/log"
DYNAMIC_PREFIXES: Final[tuple[str, ...]] = ("$", "`", "$(")
"""Leading characters that make a token's value unknowable before execution."""


@dataclass(frozen=True, slots=True)
class DangerFinding:
    """One matched category and the excerpt that matched it.

    The excerpt is included because a guard that only says "dangerous" cannot be
    reviewed; showing the matched words lets a caller confirm the decision was
    about what it actually sent.
    """

    category: DangerCategory
    excerpt: str


def find_dangers(command: str) -> tuple[DangerFinding, ...]:
    """Return every danger category this command matches, one finding per category.

    An empty result means the guard recognised nothing. That is not a promise the
    command is safe, only that it matched none of the irreversible shapes this
    guard knows about.
    """

    found: dict[DangerCategory, str] = {}
    for parsed in parse_commands(command):
        _judge(parsed, found)
    return tuple(DangerFinding(category, excerpt) for category, excerpt in found.items())


def _judge(command: ShellCommand, found: dict[DangerCategory, str]) -> None:
    """Record the policy verdict for one parsed command."""

    _judge_redirects(command, found)

    if command.dynamic_name:
        found.setdefault(DangerCategory.UNRESOLVED, _describe(command))
        return

    resolved = _unwrap(command)
    if resolved is None:
        found.setdefault(DangerCategory.UNRESOLVED, _describe(command))
        return
    name, args = resolved

    if name in SHELL_COMMANDS:
        nested = _shell_payload(args)
        if nested is not None:
            for inner in parse_commands(nested):
                _judge(inner, found)
        return

    for detector in _DETECTORS:
        category = detector(name, args)
        if category is not None:
            found.setdefault(category, _describe(command))


def _judge_redirects(command: ShellCommand, found: dict[DangerCategory, str]) -> None:
    """Record a truncating redirect aimed at a protected tree.

    Checked before the command itself, because the destructive act may be the
    redirect alone: ``echo x > /etc/passwd`` empties the file while the command
    name stays innocent. ``>>`` appends and is left alone.
    """

    for redirect in command.redirects:
        if redirect.append or redirect.dynamic_target:
            continue
        if redirect.target is None:
            continue
        if _normalise(redirect.target) in SAFE_REDIRECT_TARGETS:
            continue
        if _is_inside_protected(redirect.target):
            found.setdefault(DangerCategory.REDIRECT_TRUNCATE, f"> {redirect.target}")


def _unwrap(command: ShellCommand) -> tuple[str, tuple[str, ...]] | None:
    """Strip leading wrappers until the command that does the work comes first.

    A wrapper with no operand is returned as itself: ``env`` alone prints the
    environment and ``sudo -l`` lists privileges, so neither runs anything and
    neither is unresolved. Reporting them as unknown would flag two of the most
    ordinary inspection commands there are.

    Returns ``None`` only when a wrapper's operand exists but cannot be resolved,
    because then the real command is genuinely unknown.
    """

    name = command.basename
    args = command.args
    for _ in range(MAX_UNWRAP_DEPTH):
        if name is None:
            return None
        if name not in WRAPPER_COMMANDS:
            return (name, args)
        index = _first_operand(args)
        if index is None:
            return (name, args)
        candidate = args[index]
        if _is_dynamic(candidate):
            return None
        name = posixpath.basename(candidate.replace("\\", "").strip("'\""))
        args = args[index + 1 :]
    return None


def _first_operand(args: tuple[str, ...]) -> int | None:
    """Return the index of the wrapper's operand, skipping option values.

    Two shapes must be skipped, not mistaken for the command: an option that
    consumes the next token (``timeout 30 rm`` puts ``30`` where the command
    looks like it belongs), and a bare assignment (``env FOO=1 rm`` puts ``FOO=1``
    there). Both would otherwise hide the real command behind a value.
    """

    index = 0
    while index < len(args):
        arg = args[index]
        if arg in WRAPPER_OPTIONS_WITH_VALUE:
            index += 2
            continue
        if arg.startswith("-") or _is_assignment(arg) or _is_bare_duration(arg):
            index += 1
            continue
        return index
    return None


def _is_bare_duration(token: str) -> bool:
    """Return whether a token is a bare number, as ``timeout 30 cmd`` supplies.

    ``timeout`` takes its duration positionally, so ``30`` sits exactly where the
    command would be. Skipping it is what lets the real command be seen.
    """

    return token.isdigit() or (token[:-1].isdigit() and token[-1] in "smhd")


def _is_assignment(token: str) -> bool:
    """Return whether a token is a shell-style ``NAME=VALUE`` assignment."""

    name, separator, _ = token.partition("=")
    if not separator or not name:
        return False
    return name.replace("_", "a").isalnum() and not name[0].isdigit()


def _shell_payload(args: tuple[str, ...]) -> str | None:
    """Return the command string a shell was asked to execute, if any."""

    for index, arg in enumerate(args):
        if arg == SHELL_COMMAND_FLAG and index + 1 < len(args):
            return args[index + 1]
    return None


def _detect_recursive_delete(name: str, args: tuple[str, ...]) -> DangerCategory | None:
    """Return the delete category when a forced recursive wipe hits a tree."""

    if name not in {"rm", "find"}:
        return None
    if name == "find" and not _has_flag(args, "-delete"):
        return None
    if name == "rm" and not (_has_any(args, RECURSIVE_FLAGS) and _has_any(args, FORCE_FLAGS)):
        return None
    return DangerCategory.RECURSIVE_DELETE if _targets_protected_tree(args) else None


def _detect_data_destroying(name: str, args: tuple[str, ...]) -> DangerCategory | None:
    """Return the delete category for truncate/shred/mv against a system tree."""

    if name not in {"truncate", "shred", "mv"}:
        return None
    return DangerCategory.RECURSIVE_DELETE if _targets_inside_protected(args) else None


def _detect_unresolved(name: str, args: tuple[str, ...]) -> DangerCategory | None:
    """Return the advisory category when a destructive target is unknowable.

    Two shapes qualify: the target is an expansion, or there is no target at all
    because it arrives on stdin, as in ``echo x | xargs rm -rf``.
    """

    if name not in DESTRUCTIVE_COMMANDS:
        return None
    if name == "rm" and not (_has_any(args, RECURSIVE_FLAGS) and _has_any(args, FORCE_FLAGS)):
        return None
    targets = [arg for arg in args if not arg.startswith("-")]
    if not targets:
        return DangerCategory.UNRESOLVED
    return DangerCategory.UNRESOLVED if any(_is_dynamic(arg) for arg in targets) else None


def _detect_permission_open(name: str, args: tuple[str, ...]) -> DangerCategory | None:
    """Return the permission category when a system tree is opened up."""

    operands = [arg for arg in args if not arg.startswith("-")]
    if len(operands) < 2:
        return None
    if name == "chmod":
        if not _is_world_writable_mode(operands[0]):
            return None
        targets = operands[1:]
    elif name == "chown":
        targets = operands[1:]
    else:
        return None
    return DangerCategory.PERMISSION_OPEN if any(_is_inside_protected(t) for t in targets) else None


def _detect_disk_write(name: str, args: tuple[str, ...]) -> DangerCategory | None:
    """Return the disk category for raw block-device writes."""

    if name.startswith("mkfs"):
        return DangerCategory.DISK_WRITE
    if name == "dd" and any(arg.startswith("of=/dev/") for arg in args):
        return DangerCategory.DISK_WRITE
    return None


def _detect_power_state(name: str, args: tuple[str, ...]) -> DangerCategory | None:
    """Return the power category for halt/reboot commands."""

    del args
    return DangerCategory.POWER_STATE if name in POWER_COMMANDS else None


def _detect_firewall_flush(name: str, args: tuple[str, ...]) -> DangerCategory | None:
    """Return the firewall category when every rule is dropped."""

    if name != "iptables":
        return None
    return DangerCategory.FIREWALL_FLUSH if _has_any(args, FLUSH_FLAGS) else None


def _detect_audit_tamper(name: str, args: tuple[str, ...]) -> DangerCategory | None:
    """Return the audit category when the record of events is destroyed."""

    if name == "auditctl" and "-D" in args:
        return DangerCategory.AUDIT_TAMPER
    if name == "history" and "-c" in args:
        return DangerCategory.AUDIT_TAMPER
    if name == "systemctl" and any(arg in {"stop", "disable", "mask"} for arg in args):
        return DangerCategory.AUDIT_TAMPER if "auditd" in args else None
    if name in {"rm", "truncate", "shred"} and _targets_log_root(args):
        return DangerCategory.AUDIT_TAMPER
    return None


def _detect_access_lockout(name: str, args: tuple[str, ...]) -> DangerCategory | None:
    """Return the lockout category for anything that removes the way back in.

    Three shapes: stopping, disabling or masking sshd or the firewall; taking a
    network interface down; and killing init or sshd outright. A ``restart`` is
    not among them on purpose -- restarting a service is ordinary work.
    """

    if name == "systemctl":
        verbs = [arg for arg in args if not arg.startswith("-")]
        if not verbs:
            return None
        verb = verbs[0]
        units = set(verbs[1:])
        if verb in ACCESS_REMOVING_VERBS and units & SERVICE_UNITS:
            return DangerCategory.ACCESS_LOCKOUT
        return None

    if name in {"ip", "ifconfig", "ifdown"}:
        if name == "ifdown":
            return DangerCategory.ACCESS_LOCKOUT
        tokens = [arg for arg in args if not arg.startswith("-")]
        if name == "ip" and "link" in tokens and "down" in tokens:
            return DangerCategory.ACCESS_LOCKOUT
        if name == "ifconfig" and "down" in tokens:
            return DangerCategory.ACCESS_LOCKOUT
        return None

    if name == "iptables":
        operands = [arg for arg in args if not arg.startswith("-")]
        policy_drop = "-P" in args and any(arg.upper() == "DROP" for arg in args)
        default_drop = "INPUT" in operands and "DROP" in [arg.upper() for arg in args]
        return DangerCategory.ACCESS_LOCKOUT if policy_drop or default_drop else None

    if name in {"kill", "pkill", "killall"}:
        targets = [arg for arg in args if not arg.startswith("-")]
        if name == "kill" and "1" in targets:
            return DangerCategory.ACCESS_LOCKOUT
        if name in {"pkill", "killall"} and any("sshd" in target for target in targets):
            return DangerCategory.ACCESS_LOCKOUT
        return None

    if name == "swapoff" and "-a" in args:
        return DangerCategory.ACCESS_LOCKOUT

    if name == "crontab" and "-r" in args:
        return DangerCategory.ACCESS_LOCKOUT

    if name in IDENTITY_COMMANDS and ("-r" in args or "--remove" in args):
        return DangerCategory.ACCESS_LOCKOUT

    return None


def _detect_mass_destroy(name: str, args: tuple[str, ...]) -> DangerCategory | None:
    """Return the delete category for commands that wipe many things at once.

    ``docker system prune -a --volumes`` and ``rsync --delete`` destroy more in
    one invocation than any ``rm`` would, and neither names a path the guard could
    reason about.
    """

    if name == "docker":
        tokens = [arg for arg in args if not arg.startswith("-")]
        if any(token in DANGEROUS_DOCKER_VERBS for token in tokens):
            return DangerCategory.RECURSIVE_DELETE
        if "rm" in tokens and any(arg.startswith("$(") or arg.startswith("`") for arg in args):
            return DangerCategory.UNRESOLVED
        return None

    if name == "rsync" and _has_any(args, MASS_DELETE_FLAGS):
        return DangerCategory.RECURSIVE_DELETE

    return None


def _detect_archive_extraction(name: str, args: tuple[str, ...]) -> DangerCategory | None:
    """Return the delete category for an archive unpacked over a system tree.

    ``tar xzf x.tar.gz -C /`` overwrites files wherever the archive says, so the
    damage is decided by the archive's contents rather than by the command line.
    """

    if name not in {"tar", "unzip"}:
        return None
    if name == "tar" and not any(arg in {"-C", "--directory"} for arg in args):
        return None
    if name == "unzip" and not any(arg in {"-d"} for arg in args):
        return None
    return (
        DangerCategory.RECURSIVE_DELETE
        if any(_is_inside_protected(arg) for arg in args if not arg.startswith("-"))
        else None
    )


_DETECTORS: Final[tuple[Detector, ...]] = (
    _detect_recursive_delete,
    _detect_data_destroying,
    _detect_unresolved,
    _detect_access_lockout,
    _detect_mass_destroy,
    _detect_archive_extraction,
    _detect_permission_open,
    _detect_disk_write,
    _detect_power_state,
    _detect_firewall_flush,
    _detect_audit_tamper,
)
"""Every policy rule, in report order. Declared as data so adding one is one line."""


def _has_flag(args: tuple[str, ...], flag: str) -> bool:
    """Return whether one exact flag token is present."""

    return any(arg == flag for arg in args)


def _has_any(args: tuple[str, ...], flags: frozenset[str]) -> bool:
    """Return whether any flag is present, including bundled short options.

    ``-rf`` carries both ``-r`` and ``-f``; comparing whole tokens alone would
    miss it, which is how ``chmod -R 777`` slipped through once already.
    """

    for arg in args:
        if arg in flags:
            return True
        if arg.startswith("-") and not arg.startswith("--"):
            letters = set(arg[1:])
            if any(len(flag) == 2 and flag[1] in letters for flag in flags):
                return True
    return False


def _is_dynamic(token: str) -> bool:
    """Return whether a token's value is only decided when the shell runs it."""

    return token.startswith(DYNAMIC_PREFIXES) or "$(" in token or "`" in token


def _normalise(target: str) -> str:
    """Return a comparison-ready absolute path, without quoting or trailing slash."""

    cleaned = target.replace("\\", "").strip("'\"")
    if cleaned in WHOLE_TREE_TARGETS:
        return cleaned
    return posixpath.normpath(cleaned) if cleaned.startswith("/") else cleaned


def _targets_protected_tree(args: tuple[str, ...]) -> bool:
    """Return whether any target is a protected tree or a whole-home shorthand.

    ``~`` and ``/*`` are not system roots but mean the same thing to ``rm``, so
    both vocabularies are consulted here.
    """

    return any(
        _normalise(arg) in SYSTEM_ROOTS or _normalise(arg) in WHOLE_TREE_TARGETS
        for arg in args
        if not arg.startswith("-")
    )


def _targets_inside_protected(args: tuple[str, ...]) -> bool:
    """Return whether any target sits inside a protected tree.

    ``truncate -s0 /etc/passwd`` targets a file, not the tree, but emptying it is
    just as unrecoverable, so containment counts here.
    """

    return any(_is_inside_protected(arg) for arg in args if not arg.startswith("-"))


def _is_inside_protected(target: str) -> bool:
    """Return whether this path is a protected tree or lives under one."""

    normalised = _normalise(target)
    if normalised in WHOLE_TREE_TARGETS or normalised in SYSTEM_ROOTS:
        return True
    return any(normalised.startswith(f"{root}/") for root in SYSTEM_ROOTS if root != "/")


def _targets_log_root(args: tuple[str, ...]) -> bool:
    """Return whether a command removes the log tree itself rather than a subdir.

    ``rm -rf /var/log`` and ``rm -rf /var/log/*`` destroy the audit trail;
    ``rm -rf /var/log/old`` is routine rotation and must stay allowed.
    """

    destruction_targets = {LOG_TREE, f"{LOG_TREE}/*"}
    return any(_normalise(arg) in destruction_targets for arg in args if not arg.startswith("-"))


def _is_world_writable_mode(mode: str) -> bool:
    """Return whether a chmod mode grants write access to everyone."""

    return mode in WORLD_WRITABLE_MODES or mode.endswith("777")


def _describe(command: ShellCommand) -> str:
    """Return a reviewable excerpt for one parsed command."""

    parts = [command.name or "<dynamic>", *command.args]
    return " ".join(parts).strip()


__all__ = [
    "DESTRUCTIVE_COMMANDS",
    "SYSTEM_ROOTS",
    "WHOLE_TREE_TARGETS",
    "WORLD_WRITABLE_MODES",
    "WRAPPER_COMMANDS",
    "WRAPPER_OPTIONS_WITH_VALUE",
    "DangerFinding",
    "find_dangers",
]
