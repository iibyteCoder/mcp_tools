"""异步 Neo4j 连接管理器。"""

from typing import Any

from neo4j import AsyncDriver, AsyncGraphDatabase

from mcp_neo4j.config import Neo4jConfig


class Neo4jConnection:
    """异步 Neo4j 数据库连接管理器。

    使用 neo4j 官方异步驱动处理连接生命周期、查询执行和错误处理，
    实现非阻塞 I/O 操作。
    """

    def __init__(self, config: Neo4jConfig | None = None):
        """初始化连接管理器。

        参数:
            config: Neo4j 配置。未提供时使用默认值。
        """
        self._config = config or Neo4jConfig()
        self._driver: AsyncDriver | None = None

    @property
    def config(self) -> Neo4jConfig:
        """获取当前配置。"""
        return self._config

    @property
    def is_connected(self) -> bool:
        """检查驱动是否活跃。"""
        return self._driver is not None

    async def connect(self, **overrides: Any) -> None:
        """建立数据库连接。

        参数:
            **overrides: 本次连接的配置覆盖项。

        异常:
            ConnectionError: 连接失败时抛出。
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
            # 验证连接
            await self._driver.verify_connectivity()
        except Exception as e:
            self._driver = None
            raise ConnectionError(f"连接 Neo4j 失败: {e}") from e

    async def disconnect(self) -> None:
        """关闭数据库连接。"""
        if self._driver is not None:
            await self._driver.close()
        self._driver = None

    async def execute_query(self, query: str, parameters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """异步执行 Cypher 查询。

        参数:
            query: Cypher 查询字符串。
            parameters: 查询参数。

        返回:
            记录字典列表。

        异常:
            RuntimeError: 未连接数据库时抛出。
        """
        if not self.is_connected:
            raise RuntimeError("未连接数据库，请先调用 connect()")

        async with self._driver.session(database=self._config.database) as session:
            result = await session.run(query, parameters or {})
            records = await result.data()
            return records

    async def execute_write(self, query: str, parameters: dict[str, Any] | None = None) -> dict[str, Any]:
        """异步执行写入查询（CREATE、MERGE、DELETE、SET）。

        参数:
            query: Cypher 查询字符串。
            parameters: 查询参数。

        返回:
            包含摘要信息的字典。

        异常:
            RuntimeError: 未连接数据库时抛出。
        """
        if not self.is_connected:
            raise RuntimeError("未连接数据库，请先调用 connect()")

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
        """获取数据库中所有节点标签列表。"""
        results = await self.execute_query("CALL db.labels() YIELD label RETURN label")
        return [r["label"] for r in results]

    async def get_relationship_types(self) -> list[str]:
        """获取数据库中所有关系类型列表。"""
        results = await self.execute_query("CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType")
        return [r["relationshipType"] for r in results]

    async def get_property_keys(self) -> list[str]:
        """获取数据库中所有属性键列表。"""
        results = await self.execute_query("CALL db.propertyKeys() YIELD propertyKey RETURN propertyKey")
        return [r["propertyKey"] for r in results]

    async def get_node_schema(self, label: str) -> list[dict[str, Any]]:
        """获取指定标签节点的结构信息。

        参数:
            label: 要查看的节点标签。

        返回:
            属性信息列表。
        """
        self._validate_identifier(label)
        results = await self.execute_query(
            f"MATCH (n:`{label}`) WITH n LIMIT 100 UNWIND keys(n) AS key "
            "RETURN DISTINCT key AS property, head([n WHERE n[key] IS NOT NULL]) AS sample"
        )
        return results

    async def get_database_info(self) -> dict[str, Any]:
        """获取数据库信息。"""
        results = await self.execute_query("CALL db.info() YIELD name, id RETURN name, id")
        if results:
            return results[0]
        return {}

    def _validate_identifier(self, identifier: str) -> None:
        """验证标识符以防止 Cypher 注入。

        参数:
            identifier: 要验证的标识符。

        异常:
            ValueError: 标识符无效时抛出。
        """
        if not identifier or not identifier.replace("_", "").isalnum():
            raise ValueError(f"无效的标识符: {identifier}")
