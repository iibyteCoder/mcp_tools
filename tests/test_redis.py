"""Redis MCP 工具集成测试 — 需要本地/可访问的 Redis 实例."""

import pytest

from mcp_redis.config import RedisConfig
from mcp_redis.connection import RedisConnection
from mcp_redis.tools import build_dispatch, get_all_definitions
from tests.conftest import REDIS_CONFIG

TEST_PREFIX = "_mcp_test_"


# ── Fixtures ──


async def _try_connect() -> RedisConnection:
    cfg = RedisConfig(**REDIS_CONFIG)
    conn = RedisConnection(cfg)
    try:
        await conn.connect()
        return conn
    except Exception as e:
        pytest.skip(f"Redis 不可用: {e}")


@pytest.fixture
async def conn():
    conn = await _try_connect()
    yield conn
    # 清理所有测试 key
    try:
        keys, _ = await conn.scan_keys(f"{TEST_PREFIX}*")
        if keys:
            await conn.key_delete(*keys)
    except Exception:
        pass
    await conn.disconnect()


@pytest.fixture
async def dispatch(conn):
    return build_dispatch(conn)


# ── 工具定义 ──


def test_tool_definitions():
    tools = get_all_definitions()
    assert len(tools) == 53
    assert len({t.name for t in tools}) == 53  # 无重复


# ── 连接管理 ──


@pytest.mark.asyncio
async def test_status(dispatch):
    result = await dispatch["redis_status"]({})
    assert result.status.value == "success"
    assert result.data["connected"] is True  # type: ignore[index]


@pytest.mark.asyncio
async def test_ping(dispatch):
    result = await dispatch["redis_ping"]({})
    assert result.data["pong"] is True  # type: ignore[index]


@pytest.mark.asyncio
async def test_disconnect_reconnect():
    cfg = RedisConfig(**REDIS_CONFIG)
    conn = RedisConnection(cfg)
    try:
        await conn.connect()
        assert conn.is_connected
        await conn.disconnect()
        assert not conn.is_connected
        await conn.connect()
        assert conn.is_connected
    except Exception as e:
        pytest.skip(f"Redis 不可用: {e}")
    finally:
        await conn.disconnect()


# ── Key 管理 ──


@pytest.mark.asyncio
async def test_set_and_exists(dispatch):
    k = f"{TEST_PREFIX}exists"
    await dispatch["redis_set"]({"key": k, "value": "hello"})
    result = await dispatch["redis_exists"]({"key": k})
    assert result.data["exists"] is True  # type: ignore[index]

    result2 = await dispatch["redis_exists"]({"key": f"{TEST_PREFIX}nonexist"})
    assert result2.data["exists"] is False  # type: ignore[index]


@pytest.mark.asyncio
async def test_type(dispatch):
    k = f"{TEST_PREFIX}type"
    await dispatch["redis_set"]({"key": k, "value": "x"})
    result = await dispatch["redis_type"]({"key": k})
    assert result.data["type"] == "string"  # type: ignore[index]


@pytest.mark.asyncio
async def test_ttl_and_expire(dispatch):
    k = f"{TEST_PREFIX}ttl"
    await dispatch["redis_set"]({"key": k, "value": "x", "ex": 60})
    r1 = await dispatch["redis_ttl"]({"key": k})
    assert 0 < r1.data["ttl"] <= 60  # type: ignore[index]

    await dispatch["redis_persist"]({"key": k})
    r2 = await dispatch["redis_ttl"]({"key": k})
    assert r2.data["ttl"] == -1  # 永久  # type: ignore[index]


@pytest.mark.asyncio
async def test_rename(dispatch):
    k1, k2 = f"{TEST_PREFIX}rn1", f"{TEST_PREFIX}rn2"
    await dispatch["redis_set"]({"key": k1, "value": "data"})
    await dispatch["redis_rename"]({"key": k1, "newkey": k2})
    e1 = await dispatch["redis_exists"]({"key": k1})
    e2 = await dispatch["redis_exists"]({"key": k2})
    assert e1.data["exists"] is False  # type: ignore[index]
    assert e2.data["exists"] is True  # type: ignore[index]


@pytest.mark.asyncio
async def test_delete(dispatch):
    keys = [f"{TEST_PREFIX}del_{i}" for i in range(3)]
    for k in keys:
        await dispatch["redis_set"]({"key": k, "value": "x"})
    result = await dispatch["redis_delete"]({"keys": keys})
    assert result.data["deleted"] == 3  # type: ignore[index]


@pytest.mark.asyncio
async def test_keys_scan(dispatch):
    """验证 SCAN 分页."""
    # 创建几个测试 key
    for i in range(5):
        await dispatch["redis_set"]({"key": f"{TEST_PREFIX}scan_{i}", "value": str(i)})
    result = await dispatch["redis_keys"]({"pattern": f"{TEST_PREFIX}scan_*"})
    assert result.status.value == "success"
    assert len(result.data["keys"]) >= 5  # type: ignore[index]


# ── String 操作 ──


@pytest.mark.asyncio
async def test_get_set(dispatch):
    k = f"{TEST_PREFIX}str"
    await dispatch["redis_set"]({"key": k, "value": "world"})
    r = await dispatch["redis_get"]({"key": k})
    assert r.data["value"] == "world"  # type: ignore[index]


@pytest.mark.asyncio
async def test_get_nonexistent(dispatch):
    r = await dispatch["redis_get"]({"key": f"{TEST_PREFIX}nonexist_key"})
    assert r.data["value"] is None  # type: ignore[index]


@pytest.mark.asyncio
async def test_set_nx_xx(dispatch):
    k = f"{TEST_PREFIX}nx"
    # nx: 不存在时写入
    r1 = await dispatch["redis_set"]({"key": k, "value": "first", "nx": True})
    assert r1.data["ok"] is True  # type: ignore[index]
    # nx: 已存在时拒绝
    r2 = await dispatch["redis_set"]({"key": k, "value": "second", "nx": True})
    assert r2.data["ok"] is False  # type: ignore[index]
    # xx: 存在时写入
    r3 = await dispatch["redis_set"]({"key": k, "value": "second", "xx": True})
    assert r3.data["ok"] is True  # type: ignore[index]


@pytest.mark.asyncio
async def test_mget_mset(dispatch):
    mapping = {f"{TEST_PREFIX}mg_{i}": f"v{i}" for i in range(3)}
    await dispatch["redis_mset"]({"mapping": mapping})
    keys = list(mapping.keys())
    r = await dispatch["redis_mget"]({"keys": keys})
    assert r.data["hit"] == 3  # type: ignore[index]
    assert r.data["values"][keys[0]] == "v0"  # type: ignore[index]


@pytest.mark.asyncio
async def test_incr(dispatch):
    k = f"{TEST_PREFIX}incr"
    r1 = await dispatch["redis_incr"]({"key": k})
    assert r1.data["result"] == 1  # type: ignore[index]
    r2 = await dispatch["redis_incr"]({"key": k, "amount": 5})
    assert r2.data["result"] == 6  # type: ignore[index]
    r3 = await dispatch["redis_incr"]({"key": k, "amount": -2})
    assert r3.data["result"] == 4  # type: ignore[index]


@pytest.mark.asyncio
async def test_append_strlen(dispatch):
    k = f"{TEST_PREFIX}app"
    await dispatch["redis_set"]({"key": k, "value": "Hello"})
    r = await dispatch["redis_append"]({"key": k, "value": " World"})
    assert r.data["total_len"] == 11  # type: ignore[index]
    r2 = await dispatch["redis_get"]({"key": k})
    assert r2.data["value"] == "Hello World"  # type: ignore[index]
    r3 = await dispatch["redis_strlen"]({"key": k})
    assert r3.data["length"] == 11  # type: ignore[index]


# ── Hash 操作 ──


@pytest.mark.asyncio
async def test_hash_crud(dispatch):
    k = f"{TEST_PREFIX}h"
    # HSET
    await dispatch["redis_hset"]({"key": k, "mapping": {"a": "1", "b": "2"}})
    # HGET
    r = await dispatch["redis_hget"]({"key": k, "field": "a"})
    assert r.data["value"] == "1"  # type: ignore[index]
    # HEXISTS
    r2 = await dispatch["redis_hexists"]({"key": k, "field": "a"})
    assert r2.data["exists"] is True  # type: ignore[index]
    # HKEYS
    r3 = await dispatch["redis_hkeys"]({"key": k})
    assert set(r3.data["fields"]) == {"a", "b"}  # type: ignore[index]
    # HVALS
    r4 = await dispatch["redis_hvals"]({"key": k})
    assert set(r4.data["values"]) == {"1", "2"}  # type: ignore[index]
    # HLEN
    r5 = await dispatch["redis_hlen"]({"key": k})
    assert r5.data["length"] == 2  # type: ignore[index]
    # HGETALL
    r6 = await dispatch["redis_hgetall"]({"key": k})
    assert r6.data["count"] == 2  # type: ignore[index]
    # HDEL
    r7 = await dispatch["redis_hdel"]({"key": k, "fields": ["a"]})
    assert r7.data["deleted"] == 1  # type: ignore[index]
    r8 = await dispatch["redis_hlen"]({"key": k})
    assert r8.data["length"] == 1  # type: ignore[index]


# ── List 操作 ──


@pytest.mark.asyncio
async def test_list_ops(dispatch):
    k = f"{TEST_PREFIX}l"
    # LPUSH
    r1 = await dispatch["redis_lpush"]({"key": k, "values": ["c", "b", "a"]})
    assert r1.data["length"] == 3  # type: ignore[index]
    # RPUSH
    r2 = await dispatch["redis_rpush"]({"key": k, "values": ["d", "e"]})
    assert r2.data["length"] == 5  # type: ignore[index]
    # LRANGE
    r3 = await dispatch["redis_lrange"]({"key": k, "start": 0, "stop": -1})
    assert r3.data["values"] == ["a", "b", "c", "d", "e"]  # type: ignore[index]
    # LINDEX
    r4 = await dispatch["redis_lindex"]({"key": k, "index": 0})
    assert r4.data["value"] == "a"  # type: ignore[index]
    # LLEN
    r5 = await dispatch["redis_llen"]({"key": k})
    assert r5.data["length"] == 5  # type: ignore[index]
    # LPOP
    r6 = await dispatch["redis_lpop"]({"key": k, "count": 2})
    assert r6.data["values"] == ["a", "b"]  # type: ignore[index]
    # RPOP
    r7 = await dispatch["redis_rpop"]({"key": k})
    assert r7.data["values"] == ["e"]  # type: ignore[index]
    # LTRIM
    await dispatch["redis_ltrim"]({"key": k, "start": 0, "stop": 0})
    r8 = await dispatch["redis_lrange"]({"key": k, "start": 0, "stop": -1})
    assert r8.data["values"] == ["c"]  # type: ignore[index]


# ── Set 操作 ──


@pytest.mark.asyncio
async def test_set_ops(dispatch):
    k = f"{TEST_PREFIX}s"
    r1 = await dispatch["redis_sadd"]({"key": k, "members": ["x", "y", "z"]})
    assert r1.data["added"] == 3  # type: ignore[index]
    r2 = await dispatch["redis_sadd"]({"key": k, "members": ["x"]})  # 重复
    assert r2.data["added"] == 0  # type: ignore[index]
    r3 = await dispatch["redis_scard"]({"key": k})
    assert r3.data["count"] == 3  # type: ignore[index]
    r4 = await dispatch["redis_sismember"]({"key": k, "member": "y"})
    assert r4.data["is_member"] is True  # type: ignore[index]
    r5 = await dispatch["redis_srem"]({"key": k, "members": ["x", "y"]})
    assert r5.data["removed"] == 2  # type: ignore[index]
    r6 = await dispatch["redis_smembers"]({"key": k})
    assert r6.data["members"] == ["z"]  # type: ignore[index]


# ── Sorted Set 操作 ──


@pytest.mark.asyncio
async def test_zset_ops(dispatch):
    k = f"{TEST_PREFIX}z"
    r1 = await dispatch["redis_zadd"]({"key": k, "mapping": {"a": 1.0, "b": 3.0, "c": 2.0}})
    assert r1.data["added"] == 3  # type: ignore[index]
    r2 = await dispatch["redis_zcard"]({"key": k})
    assert r2.data["count"] == 3  # type: ignore[index]
    r3 = await dispatch["redis_zscore"]({"key": k, "member": "b"})
    assert r3.data["score"] == 3.0  # type: ignore[index]
    r4 = await dispatch["redis_zrank"]({"key": k, "member": "a"})
    assert r4.data["rank"] == 0  # 最小 score  # type: ignore[index]
    r5 = await dispatch["redis_zrevrank"]({"key": k, "member": "b"})
    assert r5.data["rank"] == 0  # 最大 score  # type: ignore[index]
    r6 = await dispatch["redis_zrange"]({"key": k, "start": 0, "stop": -1})
    assert r6.data["members"] == ["a", "c", "b"]  # type: ignore[index]
    r7 = await dispatch["redis_zrevrange"]({"key": k, "start": 0, "stop": -1, "with_scores": True})
    assert len(r7.data["members"]) == 3  # type: ignore[index]
    # ZREM
    r8 = await dispatch["redis_zrem"]({"key": k, "members": ["a", "c"]})
    assert r8.data["removed"] == 2  # type: ignore[index]
    r9 = await dispatch["redis_zcard"]({"key": k})
    assert r9.data["count"] == 1  # type: ignore[index]


# ── 服务器信息 ──


@pytest.mark.asyncio
async def test_info(dispatch):
    result = await dispatch["redis_info"]({"section": "server"})
    assert result.status.value == "success"
    assert "redis_version" in result.data["info"]  # type: ignore[index]


@pytest.mark.asyncio
async def test_dbsize(dispatch):
    result = await dispatch["redis_dbsize"]({})
    assert result.status.value == "success"
    assert isinstance(result.data["dbsize"], int)  # type: ignore[index]


@pytest.mark.asyncio
async def test_flushdb_no_confirm(dispatch):
    """未确认时拒绝执行."""
    result = await dispatch["redis_flushdb"]({"confirm": False})
    assert result.status.value == "error"


# ── Pipeline ──


@pytest.mark.asyncio
async def test_pipeline(dispatch):
    k = f"{TEST_PREFIX}pipe"
    result = await dispatch["redis_pipeline"](
        {
            "commands": [
                ["SET", k, "pipe_val"],
                ["GET", k],
                ["STRLEN", k],
                ["DEL", k],
            ],
        }
    )
    assert result.status.value == "success"
    assert result.data["count"] == 4  # type: ignore[index]
    results = result.data["results"]  # type: ignore[index]
    assert "pipe_val" in results[1]["result"]  # SET 返回 OK, GET 返回 pipe_val
