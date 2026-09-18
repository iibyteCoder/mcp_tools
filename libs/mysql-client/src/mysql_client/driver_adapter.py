"""Compatibility imports for the relocated driver port and aiomysql adapter."""

from mysql_client.adapters.aiomysql import AiomysqlDriverFactory
from mysql_client.ports.driver import (
    DriverColumn,
    DriverConnection,
    DriverCursor,
    DriverFactory,
    DriverFailure,
    DriverRow,
    QueryKiller,
    driver_failure_from_exception,
)

__all__ = [
    "AiomysqlDriverFactory",
    "DriverColumn",
    "DriverConnection",
    "DriverCursor",
    "DriverFactory",
    "DriverFailure",
    "DriverRow",
    "QueryKiller",
    "driver_failure_from_exception",
]
