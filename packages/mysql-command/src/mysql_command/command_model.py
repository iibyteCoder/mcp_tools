"""Typed command and input models for the MySQL CLI."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from mysql_command.profile_models import ProfileName, ProfileSettingsPatch


class CommandGroup(str, Enum):
    """Top-level command groups in the stable command tree."""

    HELP = "help"
    PROFILE = "profile"
    SERVER = "server"
    SCHEMA = "schema"
    SQL = "sql"


class CommandAction(str, Enum):
    """Actions supported by the stable command tree."""

    HELP = "help"
    LIST = "list"
    SHOW = "show"
    SET = "set"
    VALIDATE = "validate"
    BIND = "bind"
    UNBIND = "unbind"
    RENAME = "rename"
    REMOVE = "remove"
    INSPECT = "inspect"
    CAPABILITIES = "capabilities"
    DATABASES = "databases"
    TABLES = "tables"
    DESCRIBE = "describe"
    INDEXES = "indexes"
    STATS = "stats"
    READ = "read"
    WRITE = "write"
    EXPLAIN = "explain"
    BENCHMARK = "benchmark"
    COMPARE = "compare"


class OutputMode(str, Enum):
    """Presentation mode selected by the command boundary."""

    JSON = "json"
    TEXT = "text"


class InputSource(str, Enum):
    """Source of an input document."""

    INLINE = "inline"
    FILE = "file"
    STDIN = "stdin"
    PARAMS_FILE = "params_file"


class ExitCode(IntEnum):
    """Stable process exit codes exposed by the CLI."""

    SUCCESS = 0
    INVALID_ARGUMENT = 2
    INPUT_ERROR = 3
    PROFILE_ERROR = 4
    INTERNAL_ERROR = 70


class DiagnosticErrorType(str, Enum):
    """Machine-readable diagnostic categories for command validation."""

    ARGUMENT_SYNTAX = "argument_syntax"
    UNKNOWN_COMMAND = "unknown_command"
    MUTUALLY_EXCLUSIVE_INPUTS = "mutually_exclusive_inputs"
    MISSING_SQL = "missing_sql"
    FILE_NOT_FOUND = "file_not_found"
    FILE_DECODE_ERROR = "file_decode_error"
    FILE_READ_ERROR = "file_read_error"
    INVALID_PARAMS_JSON = "invalid_params_json"
    INVALID_PARAMS_TYPE = "invalid_params_type"
    SQL_PARSE = "sql_parse"
    POLICY_VIOLATION = "policy_violation"
    PROFILE_NOT_FOUND = "profile_not_found"
    PROFILE_REGISTRY_CORRUPT = "profile_registry_corrupt"
    PROFILE_REGISTRY_VERSION = "profile_registry_version_unsupported"
    PROFILE_REGISTRY_LOCKED = "profile_registry_locked"
    PROFILE_CONFLICT = "profile_conflict"
    SECRET_STORE = "secret_store_error"
    PROFILE_VALIDATION = "profile_validation_failed"


class ErrorCode(str, Enum):
    """Stable error codes owned by this CLI presentation boundary."""

    INVALID_ARGUMENT = "invalid_argument"
    INPUT_ERROR = "input_error"
    UNKNOWN_COMMAND = "unknown_command"
    INVALID_SQL = "invalid_sql"
    UNSUPPORTED_SQL = "unsupported_sql"
    PROFILE_NOT_FOUND = "profile_not_found"
    PROFILE_REGISTRY_CORRUPT = "profile_registry_corrupt"
    PROFILE_REGISTRY_VERSION = "profile_registry_version_unsupported"
    PROFILE_REGISTRY_LOCKED = "profile_registry_locked"
    PROFILE_CONFLICT = "profile_conflict"
    PROFILE_INVALID = "profile_invalid"
    SECRET_STORE = "secret_store_error"
    PROFILE_VALIDATION_FAILED = "profile_validation_failed"
    INTERNAL_ERROR = "internal_error"


class DiagnosticStatus(str, Enum):
    """Outcome status for a command request that did not contact a database."""

    PARSED = "parsed"


class ParameterKind(str, Enum):
    """Supported top-level parameter document shapes."""

    OBJECT = "object"
    ARRAY = "array"


@dataclass(frozen=True, slots=True, kw_only=True)
class SqlInputSpec:
    """A validated description of where one SQL document will be read from."""

    source: InputSource
    text: str | None = None
    path: Path | None = None

    def __post_init__(self) -> None:
        if self.source is InputSource.INLINE and (self.text is None or self.path is not None):
            raise ValueError("inline SQL requires text and no path")
        if self.source is InputSource.FILE and (self.path is None or self.text is not None):
            raise ValueError("file SQL requires a path and no inline text")
        if self.source is InputSource.STDIN and (self.text is not None or self.path is not None):
            raise ValueError("stdin SQL cannot carry text or a path")
        if self.source is InputSource.PARAMS_FILE:
            raise ValueError("params-file is not a SQL input source")

    @classmethod
    def inline(cls, text: str) -> SqlInputSpec:
        """Create an inline SQL input specification."""

        return cls(source=InputSource.INLINE, text=text)

    @classmethod
    def file(cls, path: Path) -> SqlInputSpec:
        """Create a file SQL input specification."""

        return cls(source=InputSource.FILE, path=path)

    @classmethod
    def stdin(cls) -> SqlInputSpec:
        """Create a standard-input SQL input specification."""

        return cls(source=InputSource.STDIN)


@dataclass(frozen=True, slots=True, kw_only=True)
class CommandRoute:
    """One statically declared group/action route."""

    group: CommandGroup
    action: CommandAction


@dataclass(frozen=True, slots=True, kw_only=True)
class CommandRequest:
    """Validated command request handed to the diagnostic pipeline."""

    group: CommandGroup
    action: CommandAction
    output_mode: OutputMode = OutputMode.JSON
    sql_input: SqlInputSpec | None = None
    params_file: Path | None = None
    selected_profile: ProfileName | None = None
    profile_name: ProfileName | None = None
    profile_new_name: ProfileName | None = None
    profile_path: Path | None = None
    profile_settings: ProfileSettingsPatch | None = None
    profile_password: str | None = field(default=None, repr=False)
    profile_clear_password: bool = False
    profile_no_bind: bool = False


PROFILE_ROUTES: tuple[CommandRoute, ...] = (
    CommandRoute(group=CommandGroup.PROFILE, action=CommandAction.LIST),
    CommandRoute(group=CommandGroup.PROFILE, action=CommandAction.SHOW),
    CommandRoute(group=CommandGroup.PROFILE, action=CommandAction.SET),
    CommandRoute(group=CommandGroup.PROFILE, action=CommandAction.VALIDATE),
    CommandRoute(group=CommandGroup.PROFILE, action=CommandAction.BIND),
    CommandRoute(group=CommandGroup.PROFILE, action=CommandAction.UNBIND),
    CommandRoute(group=CommandGroup.PROFILE, action=CommandAction.RENAME),
    CommandRoute(group=CommandGroup.PROFILE, action=CommandAction.REMOVE),
)

SERVER_ROUTES: tuple[CommandRoute, ...] = (
    CommandRoute(group=CommandGroup.SERVER, action=CommandAction.INSPECT),
    CommandRoute(group=CommandGroup.SERVER, action=CommandAction.CAPABILITIES),
)

SCHEMA_ROUTES: tuple[CommandRoute, ...] = (
    CommandRoute(group=CommandGroup.SCHEMA, action=CommandAction.DATABASES),
    CommandRoute(group=CommandGroup.SCHEMA, action=CommandAction.TABLES),
    CommandRoute(group=CommandGroup.SCHEMA, action=CommandAction.DESCRIBE),
    CommandRoute(group=CommandGroup.SCHEMA, action=CommandAction.INDEXES),
    CommandRoute(group=CommandGroup.SCHEMA, action=CommandAction.STATS),
)

SQL_ROUTES: tuple[CommandRoute, ...] = (
    CommandRoute(group=CommandGroup.SQL, action=CommandAction.READ),
    CommandRoute(group=CommandGroup.SQL, action=CommandAction.WRITE),
    CommandRoute(group=CommandGroup.SQL, action=CommandAction.EXPLAIN),
    CommandRoute(group=CommandGroup.SQL, action=CommandAction.BENCHMARK),
    CommandRoute(group=CommandGroup.SQL, action=CommandAction.COMPARE),
)

ALL_ROUTES: tuple[CommandRoute, ...] = PROFILE_ROUTES + SERVER_ROUTES + SCHEMA_ROUTES + SQL_ROUTES
