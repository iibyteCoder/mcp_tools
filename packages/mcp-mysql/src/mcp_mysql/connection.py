"""异步 MySQL 连接管理器。"""

from typing import Any

import aiomysql

from mcp_mysql.config import MySQLConfig


class MySQLConnection:
    """异步 MySQL 数据库连接管理器。

    使用 aiomysql 处理连接生命周期、查询执行和错误处理，
    实现非阻塞 I/O 操作。
    """

    def __init__(self, config: MySQLConfig | None = None):
        """初始化连接管理器。

        参数:
            config: MySQL 配置。未提供时使用默认值。
        """
        self._config = config or MySQLConfig()
        self._pool: aiomysql.Pool | None = None

    @property
    def config(self) -> MySQLConfig:
        """获取当前配置。"""
        return self._config

    @property
    def is_connected(self) -> bool:
        """检查连接池是否活跃。"""
        return self._pool is not None and not self._pool._closed

    async def connect(self, **overrides: Any) -> None:
        """建立数据库连接池。

        参数:
            **overrides: 本次连接的配置覆盖项。

        异常:
            ConnectionError: 连接失败时抛出。
        """
        if self.is_connected:
            await self.disconnect()

        conn_params = self._config.to_connection_params()
        conn_params.update(overrides)

        # 移除空数据库名以避免错误
        if not conn_params.get("database"):
            conn_params.pop("database", None)

        # 将配置键映射到 aiomysql 参数
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
            raise ConnectionError(f"连接 MySQL 失败: {e}") from e

    async def disconnect(self) -> None:
        """关闭数据库连接池。"""
        if self._pool is not None and not self._pool._closed:
            self._pool.close()
            await self._pool.wait_closed()
        self._pool = None

    async def execute_query(self, query: str, params: tuple | None = None) -> list[dict[str, Any]]:
        """异步执行 SELECT 查询。

        参数:
            query: SQL 查询字符串。
            params: 查询参数，用于安全的参数化查询。

        返回:
            行字典列表。

        异常:
            RuntimeError: 未连接数据库时抛出。
        """
        if not self.is_connected:
            raise RuntimeError("未连接数据库，请先调用 connect()")

        async with self._pool.acquire() as conn, conn.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(query, params)
            return await cursor.fetchall()

    async def execute_update(self, query: str, params: tuple | None = None) -> dict[str, int]:
        """异步执行 INSERT、UPDATE 或 DELETE 查询。

        参数:
            query: SQL 查询字符串。
            params: 查询参数。

        返回:
            包含 affected_rows 和 last_insert_id 的字典。

        异常:
            RuntimeError: 未连接数据库时抛出。
        """
        if not self.is_connected:
            raise RuntimeError("未连接数据库，请先调用 connect()")

        async with self._pool.acquire() as conn, conn.cursor() as cursor:
            await cursor.execute(query, params)
            await conn.commit()
            return {
                "affected_rows": cursor.rowcount,
                "last_insert_id": cursor.lastrowid,
            }

    async def get_databases(self) -> list[str]:
        """获取所有数据库列表。"""
        results = await self.execute_query("SHOW DATABASES")
        return [row["Database"] for row in results]

    async def get_tables(self) -> list[str]:
        """获取当前数据库中的表列表。"""
        results = await self.execute_query("SHOW TABLES")
        if not results:
            return []
        # 键名因数据库而异，获取第一个键
        key = next(iter(results[0].keys()))
        return [row[key] for row in results]

    async def get_table_schema(self, table_name: str) -> list[dict[str, Any]]:
        """获取表的结构信息。

        参数:
            table_name: 表名。

        返回:
            字段信息字典列表。
        """
        self._validate_table_name(table_name)
        return await self.execute_query(f"DESCRIBE `{table_name}`")

    def _validate_table_name(self, table_name: str) -> None:
        """验证表名以防止 SQL 注入。

        参数:
            table_name: 要验证的表名。

        异常:
            ValueError: 表名无效时抛出。
        """
        if not table_name or not table_name.replace("_", "").isalnum():
            raise ValueError(f"无效的表名: {table_name}")
