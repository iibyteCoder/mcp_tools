"""Compatibility imports for built-in inspection queries."""

from mysql_client.sql.inspection import (
    InspectionQueryDefinition,
    build_inspection_query,
)

__all__ = ["InspectionQueryDefinition", "build_inspection_query"]
