"""Click parameter types shared by the command modules."""

from __future__ import annotations

import click

from db_cli_kit.profiles import ProfileName

PORT_RANGE = click.IntRange(min=1, max=65_535)
"""Valid TCP port.

Declared here rather than inline so the bound is stated once and both the
`--port` option and any future command agree on it.
"""

POSITIVE_SECONDS = click.FloatRange(min=0.001)
"""A strictly positive duration in seconds."""

POSITIVE_INT = click.IntRange(min=1)
"""A strictly positive count, used for limits."""


class ProfileNameType(click.ParamType):
    """Convert a CLI argument into a validated profile name."""

    name = "profile"

    def convert(
        self,
        value: object,
        param: click.Parameter | None,
        ctx: click.Context | None,
    ) -> ProfileName:
        if isinstance(value, ProfileName):
            return value
        try:
            return ProfileName(value=str(value))
        except ValueError as exc:
            self.fail(str(exc), param, ctx)
            raise AssertionError("Click ParamType.fail always raises") from exc


PROFILE_NAME = ProfileNameType()


__all__ = ["PORT_RANGE", "POSITIVE_INT", "POSITIVE_SECONDS", "PROFILE_NAME", "ProfileNameType"]
