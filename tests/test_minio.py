"""MinIO MCP 工具集成测试 — 需要本地/可访问的 MinIO 实例."""

import base64

import pytest

from mcp_minio.config import MinioConfig
from mcp_minio.connection import MinioConnection
from mcp_minio.tools import build_dispatch, get_all_definitions
from tests.conftest import MINIO_CONFIG

TEST_BUCKET = "mcp-test-bucket"
TEST_PREFIX = "mcp_test_"


async def _try_connect() -> MinioConnection:
    cfg = MinioConfig(**MINIO_CONFIG)
    conn = MinioConnection(cfg)
    try:
        await conn.connect()
        return conn
    except Exception as e:
        pytest.skip(f"MinIO 不可用: {e}")


@pytest.fixture
async def conn():
    conn = await _try_connect()
    # 确保测试 bucket 存在
    if not await conn.bucket_exists(TEST_BUCKET):
        await conn.make_bucket(TEST_BUCKET)
    yield conn
    # 清理测试数据
    try:
        objs = await conn.list_objects(TEST_BUCKET, prefix=TEST_PREFIX, recursive=True)
        for obj in objs:
            await conn.remove_object(TEST_BUCKET, obj["name"])
    except Exception:
        pass
    await conn.disconnect()


@pytest.fixture
async def dispatch(conn):
    return build_dispatch(conn)


# ── 工具定义 ──


def test_tool_definitions():
    tools = get_all_definitions()
    assert len(tools) == 15
    names = {t.name for t in tools}
    assert "minio_connect" in names
    assert "minio_put_object" in names
    assert "minio_presigned_get_url" in names


# ── 连接管理 ──


@pytest.mark.asyncio
async def test_status(dispatch):
    result = await dispatch["minio_status"]({})
    assert result.status.value == "success"
    assert result.data["connected"] is True  # type: ignore[index]
    assert "buckets" in result.data  # type: ignore[index]


@pytest.mark.asyncio
async def test_disconnect_reconnect():
    cfg = MinioConfig(**MINIO_CONFIG)
    conn = MinioConnection(cfg)
    try:
        await conn.connect()
        assert conn.is_connected
        await conn.disconnect()
        assert not conn.is_connected
        await conn.connect()
        assert conn.is_connected
    except Exception as e:
        pytest.skip(f"MinIO 不可用: {e}")
    finally:
        await conn.disconnect()


# ── Bucket 操作 ──


@pytest.mark.asyncio
async def test_list_buckets(dispatch):
    result = await dispatch["minio_list_buckets"]({})
    assert result.status.value == "success"
    assert len(result.data["buckets"]) > 0  # type: ignore[index]
    names = [b["name"] for b in result.data["buckets"]]  # type: ignore[index]
    assert "video-save" in names


@pytest.mark.asyncio
async def test_bucket_exists(dispatch):
    r1 = await dispatch["minio_bucket_exists"]({"name": "video-save"})
    assert r1.data["exists"] is True  # type: ignore[index]
    r2 = await dispatch["minio_bucket_exists"]({"name": "nonexistent-bucket-xyz-12345"})
    assert r2.data["exists"] is False  # type: ignore[index]


# ── Object 操作 ──


@pytest.mark.asyncio
async def test_put_get_object(dispatch):
    name = f"{TEST_PREFIX}hello.txt"
    content = b"Hello MinIO MCP!"
    b64_data = base64.b64encode(content).decode("utf-8")

    # PUT
    r1 = await dispatch["minio_put_object"]({
        "bucket": TEST_BUCKET, "name": name, "data": b64_data,
        "content_type": "text/plain",
    })
    assert r1.status.value == "success"

    # GET
    r2 = await dispatch["minio_get_object"]({"bucket": TEST_BUCKET, "name": name})
    assert r2.status.value == "success"
    decoded = base64.b64decode(r2.data["data"]).decode("utf-8")  # type: ignore[index]
    assert decoded == "Hello MinIO MCP!"


@pytest.mark.asyncio
async def test_stat_object(dispatch):
    name = f"{TEST_PREFIX}stat.txt"
    b64 = base64.b64encode(b"stat-test").decode()
    await dispatch["minio_put_object"]({"bucket": TEST_BUCKET, "name": name, "data": b64})

    r = await dispatch["minio_stat_object"]({"bucket": TEST_BUCKET, "name": name})
    assert r.data["exists"] is True  # type: ignore[index]
    assert r.data["stat"]["size"] == 9  # type: ignore[index]

    r2 = await dispatch["minio_stat_object"]({"bucket": TEST_BUCKET, "name": f"{TEST_PREFIX}nonexist"})
    assert r2.data["exists"] is False  # type: ignore[index]


@pytest.mark.asyncio
async def test_list_objects(dispatch):
    # 创建多个测试对象
    for i in range(3):
        b64 = base64.b64encode(f"data{i}".encode()).decode()
        await dispatch["minio_put_object"]({"bucket": TEST_BUCKET, "name": f"{TEST_PREFIX}list_{i}.txt", "data": b64})

    r = await dispatch["minio_list_objects"]({"bucket": TEST_BUCKET, "prefix": TEST_PREFIX})
    assert r.status.value == "success"
    assert len(r.data["objects"]) >= 3  # type: ignore[index]


@pytest.mark.asyncio
async def test_copy_object(dispatch):
    src = f"{TEST_PREFIX}copy_src.txt"
    dst = f"{TEST_PREFIX}copy_dst.txt"
    b64 = base64.b64encode(b"copy-me").decode()
    await dispatch["minio_put_object"]({"bucket": TEST_BUCKET, "name": src, "data": b64})

    r = await dispatch["minio_copy_object"]({
        "src_bucket": TEST_BUCKET, "src_name": src,
        "dst_bucket": TEST_BUCKET, "dst_name": dst,
    })
    assert r.status.value == "success"

    # 验证目标存在
    r2 = await dispatch["minio_stat_object"]({"bucket": TEST_BUCKET, "name": dst})
    assert r2.data["exists"] is True  # type: ignore[index]


@pytest.mark.asyncio
async def test_remove_object(dispatch):
    name = f"{TEST_PREFIX}remove.txt"
    b64 = base64.b64encode(b"delete-me").decode()
    await dispatch["minio_put_object"]({"bucket": TEST_BUCKET, "name": name, "data": b64})

    r = await dispatch["minio_remove_object"]({"bucket": TEST_BUCKET, "name": name})
    assert r.status.value == "success"

    r2 = await dispatch["minio_stat_object"]({"bucket": TEST_BUCKET, "name": name})
    assert r2.data["exists"] is False  # type: ignore[index]


# ── Presigned URL ──


@pytest.mark.asyncio
async def test_presigned_get_url(dispatch):
    name = f"{TEST_PREFIX}presign.txt"
    b64 = base64.b64encode(b"presign").decode()
    await dispatch["minio_put_object"]({"bucket": TEST_BUCKET, "name": name, "data": b64})

    r = await dispatch["minio_presigned_get_url"]({"bucket": TEST_BUCKET, "name": name, "expires": 60})
    assert r.status.value == "success"
    assert r.data["url"].startswith("http")  # type: ignore[index]
    assert r.data["expires"] == 60  # type: ignore[index]


@pytest.mark.asyncio
async def test_presigned_put_url(dispatch):
    r = await dispatch["minio_presigned_put_url"]({"bucket": TEST_BUCKET, "name": f"{TEST_PREFIX}upload.via.url", "expires": 120})
    assert r.status.value == "success"
    assert r.data["url"].startswith("http")  # type: ignore[index]
