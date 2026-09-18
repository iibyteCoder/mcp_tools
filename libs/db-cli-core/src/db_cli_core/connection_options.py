"""Single-source Click option declarations shared by root and profile commands."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import click

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable


@dataclass(frozen=True)
class ConnectionOptionSpec:
    declarations: tuple[str, ...]
    help: str
    parameter_type: Any = None

    def option(self) -> click.Option:
        attributes: dict[str, Any] = {"help": self.help}
        if self.parameter_type is not None:
            attributes["type"] = self.parameter_type
        return click.Option(list(self.declarations), **attributes)


def connection_options(
    specifications: Iterable[ConnectionOptionSpec],
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def decorate(function: Callable[..., Any]) -> Callable[..., Any]:
        decorated = function
        for specification in reversed(tuple(specifications)):
            attributes: dict[str, Any] = {"help": specification.help}
            if specification.parameter_type is not None:
                attributes["type"] = specification.parameter_type
            decorated = click.option(*specification.declarations, **attributes)(decorated)
        return decorated

    return decorate


def build_connection_options(specifications: Iterable[ConnectionOptionSpec]) -> list[click.Option]:
    return [specification.option() for specification in specifications]
