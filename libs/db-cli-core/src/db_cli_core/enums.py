"""Stable values shared across database CLI packages."""

from enum import Enum, IntEnum


class DatabaseKind(str, Enum):
    MYSQL = "mysql"
    REDIS = "redis"


class ConnectionSource(str, Enum):
    DEFAULT = "default"
    DIRECTORY = "directory"
    PROFILE = "profile"
    EXPLICIT = "explicit"


class ProfileCommand(str, Enum):
    GROUP = "profile"
    SET = "set"
    LIST = "list"
    SHOW = "show"
    SELECT = "select"
    CURRENT = "current"
    REMOVE = "remove"
    RENAME = "rename"
    CLEAR = "clear"


class RegistryField(str, Enum):
    VERSION = "version"
    PROFILES = "profiles"
    BINDINGS = "bindings"
    NAME = "name"
    SETTINGS = "settings"
    CREDENTIAL = "credential"


class RegistryVersion(IntEnum):
    CURRENT = 1


class ProfileStorage(str, Enum):
    APPLICATION = "db-cli"
    FILE_NAME = "connections.json"
    LOCK_SUFFIX = ".lock"
    TEMPORARY_PREFIX = "connections-"
    TEMPORARY_SUFFIX = ".tmp"
    CREDENTIAL_SERVICE = "db-cli-database-connections"


class ConnectionField(str, Enum):
    PASSWORD = "password"


class JsonSchemaType(str, Enum):
    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    ARRAY = "array"
    OBJECT = "object"


class OutputMode(str, Enum):
    HUMAN = "human"
    JSON = "json"


class ReplCommand(str, Enum):
    EXIT = "exit"
    QUIT = "quit"
    HELP = "help"
