"""Immutable command catalog consumed by the Click registration layer."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, TypeVar

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Mapping
    from enum import Enum

    from mcp.types import Tool

GroupType = TypeVar("GroupType", bound="Enum")


@dataclass(frozen=True)
class CommandDescriptor:
    tool_name: str
    command_name: str
    group_name: str
    group_help: str
    description: str
    input_schema: Mapping[str, Any]


class CommandCatalog:
    """Build and validate command metadata once at process startup."""

    def __init__(self, descriptors: Iterable[CommandDescriptor]) -> None:
        items = tuple(descriptors)
        identities = {(item.group_name, item.command_name) for item in items}
        if len(identities) != len(items):
            raise ValueError("命令目录包含重复的 group/command")
        self._descriptors = items

    def __iter__(self) -> Iterator[CommandDescriptor]:
        return iter(self._descriptors)

    def __len__(self) -> int:
        return len(self._descriptors)

    @classmethod
    def from_enums(
        cls,
        definitions: Iterable[Tool],
        grouped_commands: Mapping[GroupType, tuple[Enum, ...]],
        group_help: Mapping[GroupType, str],
    ) -> CommandCatalog:
        definitions_by_name = {tool.name: tool for tool in definitions}
        descriptors: list[CommandDescriptor] = []
        for group, commands in grouped_commands.items():
            for command in commands:
                tool_name = str(command.value)
                try:
                    definition = definitions_by_name[tool_name]
                except KeyError as exc:
                    raise ValueError(f"MCP 工具定义缺失: {tool_name}") from exc
                descriptors.append(
                    CommandDescriptor(
                        tool_name=tool_name,
                        command_name=command.name.lower(),
                        group_name=str(group.value),
                        group_help=group_help[group],
                        description=definition.description or "",
                        input_schema=MappingProxyType(definition.inputSchema),
                    )
                )
        if len(descriptors) != len(definitions_by_name):
            declared = {item.tool_name for item in descriptors}
            missing = sorted(set(definitions_by_name) - declared)
            raise ValueError(f"命令枚举未覆盖 MCP 工具: {', '.join(missing)}")
        return cls(descriptors)
