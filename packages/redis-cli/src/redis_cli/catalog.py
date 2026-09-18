"""Redis command catalog assembled from explicit enums and MCP schemas."""

from __future__ import annotations

from typing import TYPE_CHECKING

from db_cli_core import CommandCatalog
from mcp_redis.tools import get_all_definitions
from redis_cli.enums import (
    RedisCommandGroup,
    RedisConnectionCommand,
    RedisHashCommand,
    RedisKeyCommand,
    RedisListCommand,
    RedisServerCommand,
    RedisSetCommand,
    RedisSortedSetCommand,
    RedisStringCommand,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from enum import Enum

GROUPED_COMMANDS: Mapping[RedisCommandGroup, tuple[Enum, ...]] = {
    RedisCommandGroup.CONNECTION: tuple(RedisConnectionCommand),
    RedisCommandGroup.KEY: tuple(RedisKeyCommand),
    RedisCommandGroup.STRING: tuple(RedisStringCommand),
    RedisCommandGroup.HASH: tuple(RedisHashCommand),
    RedisCommandGroup.LIST: tuple(RedisListCommand),
    RedisCommandGroup.SET: tuple(RedisSetCommand),
    RedisCommandGroup.ZSET: tuple(RedisSortedSetCommand),
    RedisCommandGroup.SERVER: tuple(RedisServerCommand),
}

GROUP_HELP = {
    RedisCommandGroup.CONNECTION: "连接、断开与状态",
    RedisCommandGroup.KEY: "Key 扫描与生命周期",
    RedisCommandGroup.STRING: "String 操作",
    RedisCommandGroup.HASH: "Hash 操作",
    RedisCommandGroup.LIST: "List 操作",
    RedisCommandGroup.SET: "Set 操作",
    RedisCommandGroup.ZSET: "Sorted Set 操作",
    RedisCommandGroup.SERVER: "服务信息、清库与 pipeline",
}


def build_catalog() -> CommandCatalog:
    return CommandCatalog.from_enums(get_all_definitions(), GROUPED_COMMANDS, GROUP_HELP)
