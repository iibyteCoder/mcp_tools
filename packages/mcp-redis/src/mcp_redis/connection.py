"""异步 Redis 连接管理器."""

from typing import Any

import redis.asyncio as aioredis
from redis.asyncio import Redis

from mcp_redis.config import RedisConfig


class RedisConnection:
    """异步 Redis 连接管理器.

    使用 redis-py 的异步 API, 配合 hiredis 解析器实现高性能非阻塞 I/O.
    通过连接池复用连接, 减少连接建立开销.
    """

    # SCAN 每批返回的建议数量
    SCAN_COUNT = 100

    def __init__(self, config: RedisConfig | None = None):
        self._config = config or RedisConfig()
        self._client: Redis | None = None

    @property
    def config(self) -> RedisConfig:
        """获取当前配置."""
        return self._config

    @property
    def is_connected(self) -> bool:
        """检查 Redis 客户端是否已连接."""
        return self._client is not None

    def _require_client(self) -> Redis:
        """获取 Redis 客户端, 未连接时抛出异常."""
        if self._client is None:
            raise RuntimeError("未连接 Redis, 请先调用 redis_connect")
        return self._client

    # ── 连接生命周期 ──

    async def connect(self, **overrides: Any) -> None:
        """建立 Redis 连接.

        异常:
            ConnectionError: 连接失败时抛出.
        """
        if self._client is not None:
            await self.disconnect()

        params = {
            "host": overrides.get("host", self._config.host),
            "port": overrides.get("port", self._config.port),
            "db": overrides.get("db", self._config.db),
            "username": overrides.get("username", self._config.username) or None,
            "password": overrides.get("password", self._config.password) or None,
            "socket_connect_timeout": self._config.connection_timeout,
            "socket_keepalive": True,
            "max_connections": self._config.max_connections,
            "decode_responses": True,
        }

        # 去掉空值
        params = {k: v for k, v in params.items() if v is not None or k == "db"}

        try:
            self._client = await aioredis.from_url(
                f"redis://{params['host']}:{params['port']}/{params.get('db', 0)}",
                **{k: v for k, v in params.items() if k not in ("host", "port")},
            )
            await self._client.ping()
        except Exception as e:
            self._client = None
            raise ConnectionError(f"连接 Redis 失败: {e}") from e

    async def disconnect(self) -> None:
        """关闭 Redis 连接."""
        if self._client is not None:
            await self._client.aclose()
        self._client = None

    # ── 通用 Key 操作 ──

    async def scan_keys(
        self,
        pattern: str = "*",
        *,
        skip: int = 0,
        limit: int = 0,
    ) -> tuple[list[str], int]:
        """使用 SCAN 遍历所有 key, 支持分页.

        参数:
            pattern: Glob 匹配模式 (如 "user:*").
            skip: 跳过的 key 数量.
            limit: 返回的 key 数量限制, 0 表示不限制.

        返回:
            (keys, next_cursor) — keys 为当前页的 key 列表.
        """
        client = self._require_client()
        matched: list[str] = []
        cursor = 0
        skipped = 0

        while True:
            cursor, keys = await client.scan(
                cursor=cursor,
                match=pattern,
                count=self.SCAN_COUNT,
            )

            for key in keys:
                if skipped < skip:
                    skipped += 1
                    continue
                matched.append(key)
                if limit > 0 and len(matched) >= limit:
                    return matched, cursor or -1

            if cursor == 0:
                break

        return matched, cursor

    async def key_exists(self, key: str) -> bool:
        """检查 key 是否存在."""
        client = self._require_client()
        return bool(await client.exists(key))

    async def key_type(self, key: str) -> str:
        """获取 key 的类型."""
        client = self._require_client()
        return await client.type(key)  # type: ignore[no-any-return]

    async def key_ttl(self, key: str) -> int:
        """获取 key 的剩余过期时间 (秒)."""
        client = self._require_client()
        return await client.ttl(key)  # type: ignore[no-any-return]

    async def key_expire(self, key: str, seconds: int) -> bool:
        """设置 key 的过期时间."""
        client = self._require_client()
        return bool(await client.expire(key, seconds))

    async def key_persist(self, key: str) -> bool:
        """移除 key 的过期时间, 使其永久有效."""
        client = self._require_client()
        return bool(await client.persist(key))

    async def key_rename(self, old_key: str, new_key: str) -> bool:
        """重命名 key."""
        client = self._require_client()
        return bool(await client.rename(old_key, new_key))

    async def key_delete(self, *keys: str) -> int:
        """删除一个或多个 key. 返回实际删除的 key 数量."""
        client = self._require_client()
        return await client.delete(*keys)  # type: ignore[no-any-return]

    async def key_random(self) -> str | None:
        """返回一个随机的 key."""
        client = self._require_client()
        return await client.randomkey()  # type: ignore[no-any-return]

    # ── String 操作 ──

    async def string_get(self, key: str) -> str | None:
        """获取字符串 key 的值."""
        client = self._require_client()
        return await client.get(key)  # type: ignore[no-any-return]

    async def string_set(
        self,
        key: str,
        value: str,
        *,
        ex: int | None = None,
        px: int | None = None,
        nx: bool = False,
        xx: bool = False,
    ) -> bool:
        """设置字符串 key 的值."""
        client = self._require_client()
        result = await client.set(key, value, ex=ex, px=px, nx=nx, xx=xx)
        return bool(result)

    async def string_mget(self, *keys: str) -> list[str | None]:
        """批量获取字符串 key 的值."""
        client = self._require_client()
        return await client.mget(list(keys))  # type: ignore[no-any-return]

    async def string_mset(self, mapping: dict[str, str]) -> bool:
        """批量设置字符串 key 的值."""
        client = self._require_client()
        return bool(await client.mset(mapping))

    async def string_incr(self, key: str, amount: int = 1) -> int:
        """将 key 的值增加 amount (整型)."""
        client = self._require_client()
        if amount == 1:
            return await client.incr(key)  # type: ignore[no-any-return]
        return await client.incrby(key, amount)  # type: ignore[no-any-return]

    async def string_append(self, key: str, value: str) -> int:
        """向 key 的值追加字符串, 返回追加后的总长度."""
        client = self._require_client()
        return await client.append(key, value)  # type: ignore[no-any-return]

    async def string_strlen(self, key: str) -> int:
        """获取字符串 key 的值的长度."""
        client = self._require_client()
        return await client.strlen(key)  # type: ignore[no-any-return]

    # ── Hash 操作 ──

    async def hash_get(self, key: str, field: str) -> str | None:
        """获取 hash 中指定字段的值."""
        client = self._require_client()
        return await client.hget(key, field)  # type: ignore[no-any-return]

    async def hash_set(self, key: str, mapping: dict[str, str]) -> int:
        """设置 hash 中的字段值. 返回新增的字段数."""
        client = self._require_client()
        return await client.hset(key, mapping=mapping)  # type: ignore[no-any-return]

    async def hash_get_all(self, key: str) -> dict[str, str]:
        """获取 hash 的所有字段和值."""
        client = self._require_client()
        return await client.hgetall(key)  # type: ignore[no-any-return]

    async def hash_delete(self, key: str, *fields: str) -> int:
        """删除 hash 中的指定字段. 返回实际删除的字段数."""
        client = self._require_client()
        return await client.hdel(key, *fields)  # type: ignore[no-any-return]

    async def hash_exists(self, key: str, field: str) -> bool:
        """检查 hash 中的字段是否存在."""
        client = self._require_client()
        return bool(await client.hexists(key, field))

    async def hash_keys(self, key: str) -> list[str]:
        """获取 hash 的所有字段名."""
        client = self._require_client()
        return await client.hkeys(key)  # type: ignore[no-any-return]

    async def hash_values(self, key: str) -> list[str]:
        """获取 hash 的所有字段值."""
        client = self._require_client()
        return await client.hvals(key)  # type: ignore[no-any-return]

    async def hash_length(self, key: str) -> int:
        """获取 hash 的字段数量."""
        client = self._require_client()
        return await client.hlen(key)  # type: ignore[no-any-return]

    # ── List 操作 ──

    async def list_push(self, key: str, *values: str, left: bool = True) -> int:
        """向列表头部 (left=True) 或尾部 (left=False) 添加元素.
        返回列表添加后的长度."""
        client = self._require_client()
        result = await (client.lpush(key, *values) if left else client.rpush(key, *values))
        return result  # type: ignore[no-any-return]

    async def list_pop(self, key: str, left: bool = True, count: int = 1) -> str | list[str] | None:
        """从列表头部 (left=True) 或尾部 (left=False) 弹出元素."""
        client = self._require_client()
        if count > 1:
            result = await (client.lpop(key, count) if left else client.rpop(key, count))
            return result  # type: ignore[no-any-return]
        return await (client.lpop(key) if left else client.rpop(key))  # type: ignore[no-any-return]

    async def list_range(self, key: str, start: int, stop: int) -> list[str]:
        """获取列表指定范围的元素."""
        client = self._require_client()
        return await client.lrange(key, start, stop)  # type: ignore[no-any-return]

    async def list_length(self, key: str) -> int:
        """获取列表的长度."""
        client = self._require_client()
        return await client.llen(key)  # type: ignore[no-any-return]

    async def list_index(self, key: str, index: int) -> str | None:
        """获取列表指定索引的元素."""
        client = self._require_client()
        return await client.lindex(key, index)  # type: ignore[no-any-return]

    async def list_trim(self, key: str, start: int, stop: int) -> bool:
        """裁剪列表, 只保留指定范围的元素."""
        client = self._require_client()
        return bool(await client.ltrim(key, start, stop))

    # ── Set 操作 ──

    async def set_add(self, key: str, *members: str) -> int:
        """向集合添加元素."""
        client = self._require_client()
        return await client.sadd(key, *members)  # type: ignore[no-any-return]

    async def set_remove(self, key: str, *members: str) -> int:
        """从集合移除元素."""
        client = self._require_client()
        return await client.srem(key, *members)  # type: ignore[no-any-return]

    async def set_members(self, key: str) -> list[str]:
        """获取集合的所有成员."""
        client = self._require_client()
        return list(await client.smembers(key))

    async def set_card(self, key: str) -> int:
        """获取集合的成员数量."""
        client = self._require_client()
        return await client.scard(key)  # type: ignore[no-any-return]

    async def set_is_member(self, key: str, member: str) -> bool:
        """检查元素是否为集合的成员."""
        client = self._require_client()
        return bool(await client.sismember(key, member))

    # ── Sorted Set 操作 ──

    async def zset_add(self, key: str, mapping: dict[str, float]) -> int:
        """向有序集合添加元素 (或更新 score)."""
        client = self._require_client()
        return await client.zadd(key, mapping)  # type: ignore[no-any-return]

    async def zset_remove(self, key: str, *members: str) -> int:
        """从有序集合移除元素."""
        client = self._require_client()
        return await client.zrem(key, *members)  # type: ignore[no-any-return]

    async def zset_range(
        self,
        key: str,
        start: int,
        stop: int,
        *,
        with_scores: bool = False,
        reverse: bool = False,
    ) -> list[str] | list[tuple[str, float]]:
        """获取有序集合指定范围的元素."""
        client = self._require_client()
        fn = client.zrevrange if reverse else client.zrange
        return await fn(key, start, stop, withscores=with_scores)  # type: ignore[no-any-return]

    async def zset_card(self, key: str) -> int:
        """获取有序集合的成员数量."""
        client = self._require_client()
        return await client.zcard(key)  # type: ignore[no-any-return]

    async def zset_score(self, key: str, member: str) -> float | None:
        """获取有序集合中成员的 score."""
        client = self._require_client()
        return await client.zscore(key, member)  # type: ignore[no-any-return]

    async def zset_rank(self, key: str, member: str, reverse: bool = False) -> int | None:
        """获取有序集合中成员的排名."""
        client = self._require_client()
        result = await (client.zrevrank(key, member) if reverse else client.zrank(key, member))
        return result  # type: ignore[no-any-return]

    # ── 服务端信息 ──

    async def server_info(self, section: str = "default") -> dict[str, str]:
        """获取 Redis 服务器信息."""
        client = self._require_client()
        raw: dict[str, str] = await client.info(section)
        return raw

    async def server_dbsize(self) -> int:
        """获取当前数据库的 key 数量."""
        client = self._require_client()
        return await client.dbsize()  # type: ignore[no-any-return]

    async def server_ping(self) -> bool:
        """测试与服务器的连接."""
        client = self._require_client()
        return await client.ping()  # type: ignore[no-any-return]

    async def server_flushdb(self) -> bool:
        """清空当前数据库的所有 key."""
        client = self._require_client()
        return bool(await client.flushdb())

    # ── Pipeline (批量操作) ──

    # Redis 命令别名, 处理 Python 关键字冲突
    _CMD_ALIASES: dict[str, str] = {"del": "delete"}

    async def pipeline_execute(self, commands: list[list[str]]) -> list[Any]:
        """使用管道批量执行 Redis 命令.

        参数:
            commands: 命令列表, 每条命令是 [命令名, 参数1, 参数2, ...] 格式.
                      例如: [["SET", "k1", "v1"], ["GET", "k1"]]

        返回:
            每个命令的执行结果列表.
        """
        client = self._require_client()
        pipe = client.pipeline()
        for cmd in commands:
            if not cmd:
                continue
            command = cmd[0].lower()
            command = self._CMD_ALIASES.get(command, command)
            args = cmd[1:]
            getattr(pipe, command)(*args)
        results = await pipe.execute()
        return results  # type: ignore[no-any-return]
