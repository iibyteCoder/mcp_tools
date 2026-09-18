"""MySQL command catalog assembled from explicit enums and MCP schemas."""

from __future__ import annotations

from typing import TYPE_CHECKING

from db_cli_core import CommandCatalog
from mcp_mysql.tools import get_all_definitions
from mysql_cli.enums import MySQLCommandGroup, MySQLConnectionCommand, MySQLSchemaCommand, MySQLSqlCommand

if TYPE_CHECKING:
    from collections.abc import Mapping
    from enum import Enum

GROUPED_COMMANDS: Mapping[MySQLCommandGroup, tuple[Enum, ...]] = {
    MySQLCommandGroup.CONNECTION: tuple(MySQLConnectionCommand),
    MySQLCommandGroup.SQL: tuple(MySQLSqlCommand),
    MySQLCommandGroup.SCHEMA: tuple(MySQLSchemaCommand),
}

GROUP_HELP = {
    MySQLCommandGroup.CONNECTION: "连接、断开与状态",
    MySQLCommandGroup.SQL: "分页查询与数据变更",
    MySQLCommandGroup.SCHEMA: "数据库、表与字段结构",
}


def build_catalog() -> CommandCatalog:
    return CommandCatalog.from_enums(get_all_definitions(), GROUPED_COMMANDS, GROUP_HELP)
