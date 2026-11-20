"""Structural parsing of a remote command line into its individual commands.

A regular expression can only see spelling. ``/bin/rm``, ``busybox rm`` and
``sudo -u root /usr/bin/rm`` are three spellings of one command, and matching
them textually needs a new pattern per variant. This module removes that whole
class of evasion by parsing the command line into a real syntax tree and
reporting each command as a name plus arguments.

It deliberately does **not** judge safety -- that is the policy layer's job in
``danger``. Separation matters because the parser is a general-purpose fact
source (which commands ran, with what arguments) while the policy encodes a
particular opinion about which of those are irreversible.
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

import tree_sitter_bash
from tree_sitter import Language, Parser

if TYPE_CHECKING:
    from tree_sitter import Node

DYNAMIC_NODE_TYPES: Final[frozenset[str]] = frozenset(
    {
        "command_substitution",
        "simple_expansion",
        "expansion",
        "arithmetic_expansion",
        "concatenation",
    }
)
"""Node types whose value is only decided when the shell runs the command.

``$X``, ``$(cmd)`` and ``$((...))`` all land here. A command named this way
cannot be compared against anything, which is why the policy layer reports it as
an advisory instead of pretending to know what it does.
"""

MAX_RECURSION_DEPTH: Final[int] = 8
"""Depth bound for nested payloads, so a crafted command cannot exhaust the stack."""

_LANGUAGE: Final[Language] = Language(tree_sitter_bash.language())


@dataclass(frozen=True, slots=True)
class ShellRedirect:
    """One output redirect: where it writes, and whether it appends.

    ``>`` truncates the target before anything is written, so the file's previous
    contents are gone even if the command itself fails. ``>>`` does not. That
    difference decides whether the redirect alone can destroy data.
    """

    target: str | None
    append: bool
    dynamic_target: bool


@dataclass(frozen=True, slots=True)
class ShellCommand:
    """One command from a command line, as the shell would execute it.

    ``name`` is ``None`` when the command word is produced by expansion, because
    its value does not exist until run time. ``args`` holds the remaining
    argument words in order, quotes already removed.
    """

    name: str | None
    args: tuple[str, ...]
    dynamic_name: bool
    redirects: tuple[ShellRedirect, ...] = ()

    @property
    def basename(self) -> str | None:
        """Return the command name without its directory, or ``None`` if dynamic."""

        if self.name is None:
            return None
        return posixpath.basename(self.name.replace("\\", "").strip("'\""))


OUTPUT_REDIRECT_TYPES: Final[frozenset[str]] = frozenset({"file_redirect"})
"""Node types that carry an output redirect."""

APPEND_OPERATORS: Final[frozenset[str]] = frozenset({">>", ">>|"})
"""Redirect operators that append instead of truncating."""

FD_DUPLICATION: Final[re.Pattern[str]] = re.compile(r"^(?:\d*>&\d+|&>\s*$)")
"""A redirect that names another descriptor rather than a file.

``2>&1`` sends stderr to stdout; it has no path, and treating its text as one
would invent a target called ``2``.
"""


def parse_commands(command: str) -> tuple[ShellCommand, ...]:
    """Return every command in ``command``, in source order.

    A command line that cannot be parsed at all yields an empty tuple; callers
    must treat that as "unknown", never as "safe".
    """

    parser = Parser(_LANGUAGE)
    tree = parser.parse(command.encode("utf-8"))
    found: list[ShellCommand] = []
    _collect(tree.root_node, found, depth=0)
    return tuple(found)


def _collect(node: Node, found: list[ShellCommand], depth: int) -> None:
    """Walk one subtree, appending each command encountered.

    Redirects are collected while descending, because a ``redirected_statement``
    wraps its command: the command node alone does not know what it writes to, and
    ``echo x > /etc/passwd`` would otherwise look like a harmless ``echo``.

    A redirect with no command in front of it -- ``> /etc/passwd`` -- still
    truncates the file, so a bare redirect is reported as a command with no name
    rather than dropped. Truncation happens before any command could run, so
    losing it would lose the whole finding.
    """

    if depth > MAX_RECURSION_DEPTH:
        return
    if node.type == "command":
        found.append(_to_shell_command(node, _redirects_of(node.parent)))
        return
    if node.type == "redirected_statement" and not _has_command_child(node):
        redirects = _redirects_of(node)
        if redirects:
            found.append(ShellCommand(name=None, args=(), dynamic_name=False, redirects=redirects))
        return
    for child in node.children:
        _collect(child, found, depth + 1)


def _has_command_child(node: Node) -> bool:
    """Return whether a redirected statement has a command behind the redirect."""

    return any(child.type == "command" for child in node.named_children)


def _redirects_of(node: Node | None) -> tuple[ShellRedirect, ...]:
    """Return the output redirects attached to a command, if any."""

    if node is None or node.type != "redirected_statement":
        return ()
    return tuple(
        redirect
        for child in node.named_children
        if child.type in OUTPUT_REDIRECT_TYPES
        for redirect in (_to_redirect(child),)
        if redirect is not None
    )


def _to_redirect(node: Node) -> ShellRedirect | None:
    """Convert one ``file_redirect`` node into its target and mode.

    Returns ``None`` for a file-descriptor duplication such as ``2>&1``. Those
    name another descriptor rather than a file, so treating them as targets would
    report ``cmd > /tmp/out 2>&1`` as writing to a path called ``2``.

    The raw text decides that, because the parse of ``2>&1`` yields a target node
    shaped like an ordinary word: the two forms are only distinguishable by their
    operator.
    """

    raw = _text(node)
    if FD_DUPLICATION.match(raw):
        return None

    operator = next((child for child in node.children if not child.is_named), None)
    append = operator is not None and _text(operator) in APPEND_OPERATORS
    # The target is the last named child: a leading descriptor number such as the
    # ``2`` in ``2>/tmp/err.log`` parses as a named node too, and taking the first
    # would report that number as the file being written.
    target_node = node.named_children[-1] if node.named_children else None
    if target_node is None:
        return ShellRedirect(target=None, append=append, dynamic_target=True)
    dynamic = _contains_dynamic(target_node)
    return ShellRedirect(
        target=None if dynamic else _text(target_node),
        append=append,
        dynamic_target=dynamic,
    )


def _to_shell_command(node: Node, redirects: tuple[ShellRedirect, ...] = ()) -> ShellCommand:
    """Convert one ``command`` node into its name, arguments and redirects."""

    children = node.named_children
    if not children:
        return ShellCommand(name=None, args=(), dynamic_name=True, redirects=redirects)

    name_node = children[0]
    dynamic_name = _contains_dynamic(name_node) or name_node.has_error
    name = None if dynamic_name else _text(name_node)
    args = tuple(_text(child) for child in children[1:])
    return ShellCommand(
        name=name,
        args=args,
        dynamic_name=dynamic_name,
        redirects=redirects,
    )


def _contains_dynamic(node: Node) -> bool:
    """Return whether any part of this node is decided only at run time.

    The dynamic marker may sit several levels down: ``$(cmd)`` arrives as a
    ``command_name`` wrapping a ``command_substitution``, and ``$X`` as a ``word``
    wrapping a ``simple_expansion``. Checking only the top node would report both
    as literal names and silently lose the signal.
    """

    if node.type in DYNAMIC_NODE_TYPES:
        return True
    return any(_contains_dynamic(child) for child in node.children)


def _text(node: Node) -> str:
    """Return a node's source text, stripped of the quotes the shell removes."""

    raw = node.text
    if raw is None:
        return ""
    text = raw.decode("utf-8", errors="replace")
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
        return text[1:-1]
    if text.startswith("\\"):
        return text[1:]
    return text


__all__ = [
    "APPEND_OPERATORS",
    "DYNAMIC_NODE_TYPES",
    "FD_DUPLICATION",
    "MAX_RECURSION_DEPTH",
    "OUTPUT_REDIRECT_TYPES",
    "ShellCommand",
    "ShellRedirect",
    "parse_commands",
]
