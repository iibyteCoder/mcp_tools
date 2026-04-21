"""异步 Neo4j 连接管理器."""

from typing import Any

from neo4j import AsyncDriver, AsyncGraphDatabase

from mcp_neo4j.config import Neo4jConfig


class Neo4jConnection:
    """异步 Neo4j 数据库连接管理器.

    使用 neo4j 官方异步驱动处理连接生命周期、查询执行和错误处理,
    实现非阻塞 I/O 操作.
    """

    def __init__(self, config: Neo4jConfig | None = None):
        self._config = config or Neo4jConfig()
        self._driver: AsyncDriver | None = None

    @property
    def config(self) -> Neo4jConfig:
        """获取当前配置."""
        return self._config

    @property
    def is_connected(self) -> bool:
        """检查驱动是否活跃."""
        return self._driver is not None

    def _require_driver(self) -> AsyncDriver:
        """获取驱动实例, 未连接时抛出异常.

        由需要活跃连接的方法统一调用, 集中连接检查逻辑.
        """
        if self._driver is None:
            raise RuntimeError("未连接数据库, 请先调用 connect()")
        return self._driver

    # ── 连接生命周期 ──

    async def connect(self, **overrides: Any) -> None:
        """建立数据库连接.

        异常:
            ConnectionError: 连接失败时抛出.
        """
        if self.is_connected:
            await self.disconnect()

        conn_params = self._config.to_connection_params()
        conn_params.update(overrides)

        uri = conn_params.get("uri", "bolt://localhost:7687")

        try:
            driver = AsyncGraphDatabase.driver(
                uri,
                auth=(
                    conn_params.get("user", "neo4j"),
                    conn_params.get("password", ""),
                ),
                max_connection_lifetime=conn_params.get("max_connection_lifetime", 3600),
                max_connection_pool_size=conn_params.get("max_connection_pool_size", 50),
                connection_timeout=conn_params.get("connection_timeout", 30),
            )
            await driver.verify_connectivity()
            self._driver = driver
        except Exception as e:
            self._driver = None
            raise ConnectionError(f"连接 Neo4j 失败: {e}") from e

    async def disconnect(self) -> None:
        """关闭数据库连接."""
        if self._driver is not None:
            await self._driver.close()
        self._driver = None

    # ── 查询执行 ──

    async def execute_query(
        self,
        query: str,
        parameters: dict[str, Any] | None = None,
        *,
        skip: int = 0,
        limit: int = 0,
    ) -> list[dict[str, Any]]:
        """异步执行 Cypher 查询, 支持游标级分页.

        通过驱动游标控制返回记录数, 不修改查询字符串.

        参数:
            query: Cypher 查询字符串.
            parameters: 查询参数.
            skip: 跳过的记录数 (0 = 不跳过).
            limit: 最多返回的记录数 (0 = 不限制).

        异常:
            RuntimeError: 未连接数据库时抛出.
        """
        driver = self._require_driver()

        async with driver.session(database=self._config.database) as session:
            result = await session.run(query, parameters or {})

            # 不需要分页时直接获取全部记录
            if limit <= 0 and skip <= 0:
                return list(await result.data())

            # 游标级分页: 跳过 skip 条, 取 limit 条
            records: list[dict[str, Any]] = []
            count = 0
            async for record in result:
                count += 1
                if count <= skip:
                    continue
                records.append(record.data())
                if limit > 0 and len(records) >= limit:
                    break

            return records

    async def execute_write(self, query: str, parameters: dict[str, Any] | None = None) -> dict[str, Any]:
        """异步执行写入查询 (CREATE, MERGE, DELETE, SET).

        异常:
            RuntimeError: 未连接数据库时抛出.
        """
        driver = self._require_driver()

        async with driver.session(database=self._config.database) as session:
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

    # ── 状态诊断 ──

    async def get_server_info(self) -> dict[str, Any] | None:
        """获取数据库服务器信息. 未连接时返回 None."""
        if not self.is_connected:
            return None
        driver = self._require_driver()
        info = await driver.get_server_info()
        return {
            "address": str(info.address),
            "agent": info.agent,
            "protocol_version": ".".join(str(v) for v in info.protocol_version),
        }

    def get_pool_status(self) -> dict[str, Any] | None:
        """获取连接池配置信息. 未连接时返回 None."""
        if not self.is_connected:
            return None
        return {
            "max_connection_pool_size": self._config.max_connection_pool_size,
            "connection_timeout": self._config.connection_timeout,
            "max_connection_lifetime": self._config.max_connection_lifetime,
        }

    # ── Schema 查询 ──

    async def get_labels(self) -> list[str]:
        """获取数据库中所有节点标签列表."""
        results = await self.execute_query("CALL db.labels() YIELD label RETURN label")
        return [r["label"] for r in results]

    async def get_relationship_types(self) -> list[str]:
        """获取数据库中所有关系类型列表."""
        results = await self.execute_query("CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType")
        return [r["relationshipType"] for r in results]

    async def get_property_keys(self) -> list[str]:
        """获取数据库中所有属性键列表."""
        results = await self.execute_query("CALL db.propertyKeys() YIELD propertyKey RETURN propertyKey")
        return [r["propertyKey"] for r in results]

    async def get_node_schema(self, label: str) -> list[dict[str, Any]]:
        """获取指定标签节点的结构信息."""
        self._validate_identifier(label)
        results = await self.execute_query(
            f"MATCH (n:`{label}`) WITH n LIMIT 100 UNWIND keys(n) AS key "
            "RETURN DISTINCT key AS property, head([n WHERE n[key] IS NOT NULL]) AS sample",
        )
        return results

    async def get_database_info(self) -> dict[str, Any]:
        """获取数据库信息."""
        results = await self.execute_query("CALL db.info() YIELD name, id RETURN name, id")
        if results:
            return results[0]
        return {}

    def _validate_identifier(self, identifier: str) -> None:
        """验证标识符以防止 Cypher 注入."""
        if not identifier or not identifier.replace("_", "").isalnum():
            raise ValueError(f"无效的标识符: {identifier}")
