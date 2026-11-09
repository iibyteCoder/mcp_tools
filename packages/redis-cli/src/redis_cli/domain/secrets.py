"""Secret values that never render themselves in output."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class SecretValue:
    """A secret string whose repr never exposes the text."""

    _value: str = field(repr=False)

    def reveal(self) -> str:
        """Return the secret for the boundary that must use it."""

        return self._value

    def __bool__(self) -> bool:
        return bool(self._value)


__all__ = ["SecretValue"]
