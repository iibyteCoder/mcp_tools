"""Async Neo4j connection manager."""

from typing import Any

from neo4j import AsyncDriver, AsyncGraphDatabase

from mcp_neo4j.config import Neo4jConfig


class Neo4jConnection:
    """Async Neo4j database connection manager.

    Handles connection lifecycle, query execution, and error handling
    using neo4j async driver for non-blocking I/O operations.
    """

    def __init__(self, config: Neo4jConfig | None = None):
        """Initialize connection manager.

        Args:
            config: Neo4j configuration. Uses defaults if not provided.
        """
        self._config = config or Neo4jConfig()
        self._driver: AsyncDriver | None = None

    @property
    def config(self) -> Neo4jConfig:
        """Get current configuration."""
        return self._config

    @property
    def is_connected(self) -> bool:
        """Check if driver is active."""
        return self._driver is not None

    async def connect(self, **overrides: Any) -> None:
        """Establish database connection.

        Args:
            **overrides: Configuration overrides for this connection.

        Raises:
            ConnectionError: If connection fails.
        """
        if self.is_connected:
            await self.disconnect()

        conn_params = self._config.to_connection_params()
        conn_params.update(overrides)

        uri = conn_params.get("uri", "bolt://localhost:7687")

        try:
            self._driver = AsyncGraphDatabase.driver(
                uri,
                auth=(
                    conn_params.get("user", "neo4j"),
                    conn_params.get("password", ""),
                ),
                max_connection_lifetime=conn_params.get("max_connection_lifetime", 3600),
                max_connection_pool_size=conn_params.get("max_connection_pool_size", 50),
                connection_timeout=conn_params.get("connection_timeout", 30),
            )
            # Verify connection
            await self._driver.verify_connectivity()
        except Exception as e:
            self._driver = None
            raise ConnectionError(f"Failed to connect to Neo4j: {e}") from e

    async def disconnect(self) -> None:
        """Close database connection."""
        if self._driver is not None:
            await self._driver.close()
        self._driver = None

    async def execute_query(self, query: str, parameters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Execute a Cypher query asynchronously.

        Args:
            query: Cypher query string.
            parameters: Query parameters.

        Returns:
            List of record dictionaries.

        Raises:
            RuntimeError: If not connected to database.
        """
        if not self.is_connected:
            raise RuntimeError("Not connected to database. Call connect() first.")

        async with self._driver.session(database=self._config.database) as session:
            result = await session.run(query, parameters or {})
            records = await result.data()
            return records

    async def execute_write(self, query: str, parameters: dict[str, Any] | None = None) -> dict[str, Any]:
        """Execute a write query (CREATE, MERGE, DELETE, SET) asynchronously.

        Args:
            query: Cypher query string.
            parameters: Query parameters.

        Returns:
            Dictionary with summary information.

        Raises:
            RuntimeError: If not connected to database.
        """
        if not self.is_connected:
            raise RuntimeError("Not connected to database. Call connect() first.")

        async with self._driver.session(database=self._config.database) as session:
            result = await session.run(query, parameters or {})
            summary = await result.consume()
            return {
                "nodes_created": summary.counters.nodes_created,
                "nodes_deleted": summary.counters.nodes_deleted,
                "relationships_created": summary.counters.relationships_created,
                "relationships_deleted": summary.counters.relationships_deleted,
                "properties_set": summary.counters.properties_set,
                "labels_added": summary.counters.labels_added,
                "labels_removed": summary.counters.labels_removed,
            }

    async def get_labels(self) -> list[str]:
        """Get list of all node labels in the database."""
        results = await self.execute_query("CALL db.labels() YIELD label RETURN label")
        return [r["label"] for r in results]

    async def get_relationship_types(self) -> list[str]:
        """Get list of all relationship types in the database."""
        results = await self.execute_query("CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType")
        return [r["relationshipType"] for r in results]

    async def get_property_keys(self) -> list[str]:
        """Get list of all property keys in the database."""
        results = await self.execute_query("CALL db.propertyKeys() YIELD propertyKey RETURN propertyKey")
        return [r["propertyKey"] for r in results]

    async def get_node_schema(self, label: str) -> list[dict[str, Any]]:
        """Get schema information for nodes with a specific label.

        Args:
            label: Node label to inspect.

        Returns:
            List of property information.
        """
        self._validate_identifier(label)
        results = await self.execute_query(
            f"MATCH (n:`{label}`) WITH n LIMIT 100 UNWIND keys(n) AS key "
            "RETURN DISTINCT key AS property, head([n WHERE n[key] IS NOT NULL]) AS sample"
        )
        return results

    async def get_database_info(self) -> dict[str, Any]:
        """Get database information."""
        results = await self.execute_query("CALL db.info() YIELD name, id RETURN name, id")
        if results:
            return results[0]
        return {}

    def _validate_identifier(self, identifier: str) -> None:
        """Validate identifier to prevent Cypher injection.

        Args:
            identifier: Identifier to validate.

        Raises:
            ValueError: If identifier is invalid.
        """
        if not identifier or not identifier.replace("_", "").isalnum():
            raise ValueError(f"Invalid identifier: {identifier}")
