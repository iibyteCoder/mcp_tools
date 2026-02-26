"""Async MySQL connection manager."""

from typing import Any

import aiomysql

from mcp_mysql.config import MySQLConfig


class MySQLConnection:
    """Async MySQL database connection manager.

    Handles connection lifecycle, query execution, and error handling
    using aiomysql for non-blocking I/O operations.
    """

    def __init__(self, config: MySQLConfig | None = None):
        """Initialize connection manager.

        Args:
            config: MySQL configuration. Uses defaults if not provided.
        """
        self._config = config or MySQLConfig()
        self._pool: aiomysql.Pool | None = None

    @property
    def config(self) -> MySQLConfig:
        """Get current configuration."""
        return self._config

    @property
    def is_connected(self) -> bool:
        """Check if connection pool is active."""
        return self._pool is not None and not self._pool._closed

    async def connect(self, **overrides: Any) -> None:
        """Establish database connection pool.

        Args:
            **overrides: Configuration overrides for this connection.

        Raises:
            ConnectionError: If connection fails.
        """
        if self.is_connected:
            await self.disconnect()

        conn_params = self._config.to_connection_params()
        conn_params.update(overrides)

        # Remove empty database to avoid errors
        if not conn_params.get("database"):
            conn_params.pop("database", None)

        # Map config keys to aiomysql parameters
        pool_params = {
            "host": conn_params.get("host", "localhost"),
            "port": conn_params.get("port", 3306),
            "user": conn_params.get("user", "root"),
            "password": conn_params.get("password", ""),
            "db": conn_params.get("database"),
            "charset": conn_params.get("charset", "utf8mb4"),
            "autocommit": conn_params.get("autocommit", True),
            "minsize": 1,
            "maxsize": 10,
        }

        try:
            self._pool = await aiomysql.create_pool(**pool_params)
        except Exception as e:
            raise ConnectionError(f"Failed to connect to MySQL: {e}") from e

    async def disconnect(self) -> None:
        """Close database connection pool."""
        if self._pool is not None and not self._pool._closed:
            self._pool.close()
            await self._pool.wait_closed()
        self._pool = None

    async def execute_query(self, query: str, params: tuple | None = None) -> list[dict[str, Any]]:
        """Execute a SELECT query asynchronously.

        Args:
            query: SQL query string.
            params: Query parameters for safe parameterized queries.

        Returns:
            List of row dictionaries.

        Raises:
            RuntimeError: If not connected to database.
        """
        if not self.is_connected:
            raise RuntimeError("Not connected to database. Call connect() first.")

        async with self._pool.acquire() as conn, conn.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(query, params)
            return await cursor.fetchall()

    async def execute_update(self, query: str, params: tuple | None = None) -> dict[str, int]:
        """Execute INSERT, UPDATE, or DELETE query asynchronously.

        Args:
            query: SQL query string.
            params: Query parameters.

        Returns:
            Dictionary with affected_rows and last_insert_id.

        Raises:
            RuntimeError: If not connected to database.
        """
        if not self.is_connected:
            raise RuntimeError("Not connected to database. Call connect() first.")

        async with self._pool.acquire() as conn, conn.cursor() as cursor:
            await cursor.execute(query, params)
            await conn.commit()
            return {
                "affected_rows": cursor.rowcount,
                "last_insert_id": cursor.lastrowid,
            }

    async def get_databases(self) -> list[str]:
        """Get list of all databases."""
        results = await self.execute_query("SHOW DATABASES")
        return [row["Database"] for row in results]

    async def get_tables(self) -> list[str]:
        """Get list of tables in current database."""
        results = await self.execute_query("SHOW TABLES")
        if not results:
            return []
        # Key name varies based on database, get first key
        key = next(iter(results[0].keys()))
        return [row[key] for row in results]

    async def get_table_schema(self, table_name: str) -> list[dict[str, Any]]:
        """Get schema information for a table.

        Args:
            table_name: Name of the table.

        Returns:
            List of column information dictionaries.
        """
        self._validate_table_name(table_name)
        return await self.execute_query(f"DESCRIBE `{table_name}`")

    def _validate_table_name(self, table_name: str) -> None:
        """Validate table name to prevent SQL injection.

        Args:
            table_name: Table name to validate.

        Raises:
            ValueError: If table name is invalid.
        """
        if not table_name or not table_name.replace("_", "").isalnum():
            raise ValueError(f"Invalid table name: {table_name}")
