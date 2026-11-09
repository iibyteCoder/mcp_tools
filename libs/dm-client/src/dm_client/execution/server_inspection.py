"""Read-only server identity and capability inspection over one DM connection."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Final

from dm_client.domain.enums import (
    KEY_SERVER_PARAMETERS,
    SENSITIVE_PARAMETER_MARKERS,
    InspectionKind,
    SqlStatementType,
)
from dm_client.domain.errors import QueryError
from dm_client.domain.results import (
    CapabilityFact,
    ColumnDefinition,
    DatabaseRow,
    InspectionResult,
    QueryResult,
    ServerCapabilitiesResult,
    ServerInfo,
    ServerInspectResult,
    SessionInfo,
    TargetMetadata,
)
from dm_client.execution.inspection_support import fetch_all, resolve_target, text_value, timestamp_value
from dm_client.execution.tabular import build_metadata
from dm_client.sql.inspection_queries import (
    SERVER_ALL_PARAMETERS_QUERY,
    SERVER_FILTERED_PARAMETERS_QUERY,
    SERVER_INSTANCE_QUERY,
    SERVER_VERSIONS_QUERY,
    build_server_parameters_query,
)

if TYPE_CHECKING:
    from dm_client.domain.requests import ServerParametersRequest
    from dm_client.domain.results import CapabilityValue
    from dm_client.domain.values import DatabaseValue
    from dm_client.ports.driver import DmConnection, DriverRow

SOURCE_DM_INI: Final[str] = "V$DM_INI"
SOURCE_DMPYTHON: Final[str] = "dmPython"
SOURCE_V_VERSION: Final[str] = "V$VERSION"

REDACTED_VALUE: Final[str] = "***"
_PARAMETER_VALUE_COUNT: Final[int] = 7

_PARAMETER_COLUMNS: Final[tuple[ColumnDefinition, ...]] = (
    ColumnDefinition(name="PARA_NAME", type_name="VARCHAR", nullable=False, ordinal=0),
    ColumnDefinition(name="PARA_VALUE", type_name="VARCHAR", ordinal=1),
    ColumnDefinition(name="SESS_VALUE", type_name="VARCHAR", ordinal=2),
    ColumnDefinition(name="FILE_VALUE", type_name="VARCHAR", ordinal=3),
    ColumnDefinition(name="DEFAULT_VALUE", type_name="VARCHAR", ordinal=4),
    ColumnDefinition(name="MIN_VALUE", type_name="VARCHAR", ordinal=5),
    ColumnDefinition(name="MAX_VALUE", type_name="VARCHAR", ordinal=6),
    ColumnDefinition(name="REDACTED", type_name="BOOLEAN", nullable=False, ordinal=7),
)

_INTEGER_TEXT_PATTERN: Final[re.Pattern[str]] = re.compile(r"[+-]?[0-9]+")
_DMPYTHON_FACT_NAMES: Final[frozenset[str]] = frozenset(
    {"case_sensitive", "max_identifier_length", "server_version"}
)


def run_server_inspect(
    connection: DmConnection,
    target_label: str,
    target: TargetMetadata | None,
) -> ServerInspectResult:
    """Read server identity and the connected session details."""

    started_at = datetime.now(timezone.utc)
    resolved_target = resolve_target(connection, target_label, target)
    cursor = connection.cursor()
    try:
        cursor.execute(SERVER_INSTANCE_QUERY)
        rows = fetch_all(cursor)
    finally:
        cursor.close()
    if not rows:
        raise QueryError("V$INSTANCE returned no instance row")
    metadata = build_metadata(SqlStatementType.SELECT, started_at, resolved_target, row_count=1)
    return ServerInspectResult(
        server=_server_info(rows[0]),
        session=SessionInfo(user=connection.user, schema=connection.current_schema),
        metadata=metadata,
    )


def run_server_capabilities(
    connection: DmConnection,
    target_label: str,
    target: TargetMetadata | None,
) -> ServerCapabilitiesResult:
    """Read typed server capability facts from the catalog and driver."""

    started_at = datetime.now(timezone.utc)
    resolved_target = resolve_target(connection, target_label, target)
    parameter_names = tuple(key.value for key in KEY_SERVER_PARAMETERS)
    cursor = connection.cursor()
    try:
        cursor.execute(build_server_parameters_query(len(parameter_names)), parameter_names)
        parameter_rows = fetch_all(cursor)
    finally:
        cursor.close()

    facts = _parameter_facts(parameter_rows)
    facts.extend(
        CapabilityFact(name=name, value=value, source=SOURCE_DMPYTHON)
        for name, value in (
            ("case_sensitive", connection.str_case_sensitive),
            ("max_identifier_length", connection.max_identifier_length),
            ("server_version", connection.server_version),
        )
    )
    version_banners = _version_banners(connection)
    if version_banners:
        facts.append(
            CapabilityFact(
                name="version_banners",
                value=list(version_banners),
                source=SOURCE_V_VERSION,
            )
        )
    metadata = build_metadata(SqlStatementType.SELECT, started_at, resolved_target, row_count=len(facts))
    return ServerCapabilitiesResult(facts=tuple(facts), metadata=metadata)


def run_server_parameters(
    connection: DmConnection,
    request: ServerParametersRequest,
    target_label: str,
    target: TargetMetadata | None,
) -> InspectionResult:
    """Read server parameters, redacting values whose names mark them sensitive."""

    started_at = datetime.now(timezone.utc)
    resolved_target = resolve_target(connection, target_label, target)
    cursor = connection.cursor()
    try:
        if request.name_filter is not None:
            cursor.execute(SERVER_FILTERED_PARAMETERS_QUERY, (request.name_filter,))
        elif request.include_all:
            cursor.execute(SERVER_ALL_PARAMETERS_QUERY)
        else:
            parameter_names = tuple(key.value for key in KEY_SERVER_PARAMETERS)
            cursor.execute(build_server_parameters_query(len(parameter_names)), parameter_names)
        raw_rows = fetch_all(cursor)
    finally:
        cursor.close()

    rows = _parameter_rows(raw_rows)
    metadata = build_metadata(SqlStatementType.SELECT, started_at, resolved_target, row_count=len(rows))
    query = QueryResult(columns=_PARAMETER_COLUMNS, rows=rows, metadata=metadata)
    return InspectionResult(kind=InspectionKind.SERVER_PARAMETERS, query=query)


def _parameter_rows(rows: tuple[DriverRow, ...]) -> tuple[DatabaseRow, ...]:
    result: list[DatabaseRow] = []
    for row in rows:
        if len(row) < _PARAMETER_VALUE_COUNT:
            raise QueryError("V$DM_INI returned an unexpected row shape")
        if row[0] is None:
            continue
        name = text_value(row[0])
        if _is_sensitive_parameter(name):
            result.append(
                DatabaseRow.from_values(
                    (name, REDACTED_VALUE, REDACTED_VALUE, REDACTED_VALUE, REDACTED_VALUE, REDACTED_VALUE, REDACTED_VALUE, True)
                )
            )
        else:
            result.append(DatabaseRow.from_values((name, row[1], row[2], row[3], row[4], row[5], row[6], False)))
    return tuple(result)


def _is_sensitive_parameter(name: str) -> bool:
    folded = name.upper()
    return any(marker.value in folded for marker in SENSITIVE_PARAMETER_MARKERS)


def _server_info(row: DriverRow) -> ServerInfo:
    if len(row) < 10:
        raise QueryError("V$INSTANCE returned an unexpected row shape")
    return ServerInfo(
        name=text_value(row[0]),
        instance_name=text_value(row[1]),
        host_name=text_value(row[2]),
        version=text_value(row[3]),
        db_version=text_value(row[4]),
        build_version=text_value(row[8]),
        build_time=text_value(row[9]),
        start_time=timestamp_value(row[5]),
        status=text_value(row[6]),
        mode=text_value(row[7]),
    )


def _parameter_facts(rows: tuple[DriverRow, ...]) -> list[CapabilityFact]:
    raw_values: dict[str, DatabaseValue] = {}
    for row in rows:
        if len(row) < 2 or row[0] is None:
            continue
        raw_values[text_value(row[0])] = row[1]

    facts: list[CapabilityFact] = []
    for key in KEY_SERVER_PARAMETERS:
        if key.value not in raw_values:
            continue
        name = key.value.lower()
        # The explicit driver facts below are authoritative for these names.
        if name in _DMPYTHON_FACT_NAMES:
            continue
        facts.append(
            CapabilityFact(
                name=name,
                value=_capability_value(raw_values[key.value]),
                source=SOURCE_DM_INI,
            )
        )
    return facts


def _capability_value(value: DatabaseValue) -> CapabilityValue:
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, str):
        return int(value) if _INTEGER_TEXT_PATTERN.fullmatch(value.strip()) else value
    return str(value)


def _version_banners(connection: DmConnection) -> tuple[str, ...]:
    cursor = connection.cursor()
    try:
        cursor.execute(SERVER_VERSIONS_QUERY)
        rows = fetch_all(cursor)
    finally:
        cursor.close()
    return tuple(text_value(row[0]) for row in rows if row and row[0] is not None)


__all__ = ["REDACTED_VALUE", "run_server_capabilities", "run_server_inspect", "run_server_parameters"]
