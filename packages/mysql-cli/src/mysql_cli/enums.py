"""MySQL command and application identifiers."""

from enum import Enum


class MySQLApplication(str, Enum):
    NAME = "db-mysql"
    HISTORY_FILE = ".db-mysql-history"
    USE_COMMAND = "use"


class MySQLCommandGroup(str, Enum):
    CONNECTION = "connection"
    SQL = "sql"
    SCHEMA = "schema"


class MySQLConnectionCommand(str, Enum):
    CONNECT = "mysql_connect"
    DISCONNECT = "mysql_disconnect"
    STATUS = "mysql_status"


class MySQLSqlCommand(str, Enum):
    QUERY = "mysql_query"
    EXECUTE = "mysql_execute"


class MySQLSchemaCommand(str, Enum):
    DATABASES = "mysql_list_databases"
    TABLES = "mysql_list_tables"
    DESCRIBE = "mysql_describe_table"
