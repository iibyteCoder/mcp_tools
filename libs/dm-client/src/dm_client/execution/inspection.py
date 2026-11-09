"""Dispatch for read-only server and schema inspection over one DM connection."""

from __future__ import annotations

from typing import TYPE_CHECKING

from dm_client.domain.requests import (
    SchemaConstraintsRequest,
    SchemaDatabasesRequest,
    SchemaDescribeRequest,
    SchemaIndexesRequest,
    SchemaObjectsRequest,
    SchemaStatsRequest,
    SchemaTablesRequest,
    ServerCapabilitiesRequest,
    ServerInspectRequest,
    ServerParametersRequest,
)
from dm_client.execution.schema_catalog import run_schema_constraints, run_schema_objects
from dm_client.execution.schema_inspection import (
    run_schema_databases,
    run_schema_describe,
    run_schema_indexes,
    run_schema_stats,
    run_schema_tables,
)
from dm_client.execution.server_inspection import (
    run_server_capabilities,
    run_server_inspect,
    run_server_parameters,
)

if TYPE_CHECKING:
    from dm_client.domain.requests import InspectionRequest
    from dm_client.domain.results import InspectionResponse, TargetMetadata
    from dm_client.ports.driver import DmConnection


def run_inspection(
    connection: DmConnection,
    request: InspectionRequest,
    target_label: str,
    *,
    target: TargetMetadata | None = None,
) -> InspectionResponse:
    """Dispatch one read-only inspection request to its typed implementation."""

    if isinstance(request, ServerInspectRequest):
        return run_server_inspect(connection, target_label, target)
    if isinstance(request, ServerCapabilitiesRequest):
        return run_server_capabilities(connection, target_label, target)
    if isinstance(request, ServerParametersRequest):
        return run_server_parameters(connection, request, target_label, target)
    if isinstance(request, SchemaDatabasesRequest):
        return run_schema_databases(connection, request, target_label, target)
    if isinstance(request, SchemaTablesRequest):
        return run_schema_tables(connection, request, target_label, target)
    if isinstance(request, SchemaDescribeRequest):
        return run_schema_describe(connection, request, target_label, target)
    if isinstance(request, SchemaIndexesRequest):
        return run_schema_indexes(connection, request, target_label, target)
    if isinstance(request, SchemaStatsRequest):
        return run_schema_stats(connection, request, target_label, target)
    if isinstance(request, SchemaConstraintsRequest):
        return run_schema_constraints(connection, request, target_label, target)
    if isinstance(request, SchemaObjectsRequest):
        return run_schema_objects(connection, request, target_label, target)
    raise NotImplementedError("inspection is implemented in a later batch")


__all__ = ["run_inspection"]
