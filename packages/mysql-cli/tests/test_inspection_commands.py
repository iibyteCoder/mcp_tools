from __future__ import annotations

import pytest

from mysql_cli.argument_parser import build_parser, parse_command_request
from mysql_cli.command_model import CommandAction, CommandGroup
from mysql_cli.errors import CliFailure
from mysql_client import DatabaseName, TableName


@pytest.mark.parametrize(
    ("arguments", "group", "action"),
    [
        (["server", "inspect"], CommandGroup.SERVER, CommandAction.INSPECT),
        (["server", "capabilities"], CommandGroup.SERVER, CommandAction.CAPABILITIES),
        (["schema", "databases"], CommandGroup.SCHEMA, CommandAction.DATABASES),
        (["schema", "tables", "--database", "billing"], CommandGroup.SCHEMA, CommandAction.TABLES),
        (
            ["schema", "describe", "--database", "billing", "--table", "invoices"],
            CommandGroup.SCHEMA,
            CommandAction.DESCRIBE,
        ),
        (["schema", "indexes", "--table", "invoices"], CommandGroup.SCHEMA, CommandAction.INDEXES),
        (["schema", "stats", "--table", "invoices"], CommandGroup.SCHEMA, CommandAction.STATS),
    ],
)
def test_inspection_routes_are_typed(
    arguments: list[str], group: CommandGroup, action: CommandAction
) -> None:
    request = parse_command_request(build_parser(), ["--json", *arguments])

    assert request.group is group
    assert request.action is action


def test_schema_targets_are_validated_without_database_access() -> None:
    request = parse_command_request(
        build_parser(),
        ["schema", "describe", "--database", "billing", "--table", "invoices"],
    )

    assert request.schema_database == DatabaseName(value="billing")
    assert request.schema_table == TableName(value="invoices")

    with pytest.raises(CliFailure) as missing_table:
        parse_command_request(build_parser(), ["schema", "describe"])
    assert missing_table.value.code.value == "invalid_argument"

    with pytest.raises(CliFailure) as invalid_database:
        parse_command_request(build_parser(), ["schema", "tables", "--database", "\x00"])
    assert invalid_database.value.code.value == "invalid_argument"
