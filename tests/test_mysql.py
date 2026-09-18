"""MySQL MCP 工具集成测试 — 需要本地/可访问的 MySQL 实例."""

import pytest

from mcp_mysql.config import MySQLConfig
from mcp_mysql.connection import MySQLConnection
from mcp_mysql.tools import build_dispatch, get_all_definitions
from tests.conftest import MYSQL_CONFIG

# ── Fixtures ──


async def _try_connect() -> MySQLConnection:
    """尝试连接 MySQL, 失败则跳过测试."""
    cfg = MySQLConfig(**MYSQL_CONFIG)
    conn = MySQLConnection(cfg)
    try:
        await conn.connect()
        return conn
    except Exception as e:
        pytest.skip(f"MySQL 不可用: {e}")


@pytest.fixture
async def conn():
    conn = await _try_connect()
    yield conn
    await conn.disconnect()


@pytest.fixture
async def dispatch(conn):
    return build_dispatch(conn)


# ── 工具定义 ──


def test_tool_definitions():
    """验证工具定义数量和命名规范."""
    tools = get_all_definitions()
    assert len(tools) == 8
    names = {t.name for t in tools}
    assert names == {
        "mysql_connect",
        "mysql_disconnect",
        "mysql_status",
        "mysql_query",
        "mysql_execute",
        "mysql_list_databases",
        "mysql_list_tables",
        "mysql_describe_table",
    }


# ── 连接管理 ──


@pytest.mark.asyncio
async def test_status(dispatch, conn):
    result = await dispatch["mysql_status"]({})
    assert result.status.value == "success"
    assert result.data["connected"] is True  # type: ignore[index]
    assert result.data["config"]["host"] == MYSQL_CONFIG["host"]  # type: ignore[index]


@pytest.mark.asyncio
async def test_disconnect_reconnect():
    cfg = MySQLConfig(**MYSQL_CONFIG)
    conn = MySQLConnection(cfg)
    try:
        await conn.connect()
        assert conn.is_connected
        # 断开
        await conn.disconnect()
        assert not conn.is_connected
        # 重连
        await conn.connect()
        assert conn.is_connected
    except Exception as e:
        pytest.skip(f"MySQL 不可用: {e}")
    finally:
        await conn.disconnect()


# ── 查询 ──


@pytest.mark.asyncio
async def test_query_select(dispatch):
    result = await dispatch["mysql_query"]({"query": "SELECT 1 AS one, 'hello' AS greeting"})
    assert result.status.value == "success"
    rows = result.data["rows"]  # type: ignore[index]
    assert len(rows) >= 1
    assert rows[0]["one"] == 1
    assert rows[0]["greeting"] == "hello"


@pytest.mark.asyncio
async def test_query_pagination(dispatch):
    """测试分页: 每页 2 条, 共取 >2 条记录."""
    # 确保有足够的表来分页
    result = await dispatch["mysql_query"](
        {"query": "SELECT TABLE_NAME FROM information_schema.TABLES LIMIT 5", "page": 1, "page_size": 2}
    )
    assert result.status.value == "success"
    assert len(result.data["rows"]) <= 2  # type: ignore[index]


@pytest.mark.asyncio
async def test_execute_insert_delete(dispatch):
    """测试 INSERT + DELETE 往返."""
    # 创建测试表
    await dispatch["mysql_execute"](
        {"query": "CREATE TABLE IF NOT EXISTS _mcp_test (id INT PRIMARY KEY, val VARCHAR(50))"}
    )
    try:
        # INSERT
        r1 = await dispatch["mysql_execute"]({"query": "INSERT INTO _mcp_test VALUES (1, 'a'), (2, 'b')"})
        assert r1.data["affected_rows"] == 2  # type: ignore[index]

        # 验证
        r2 = await dispatch["mysql_query"]({"query": "SELECT * FROM _mcp_test ORDER BY id"})
        assert len(r2.data["rows"]) == 2  # type: ignore[index]

        # DELETE
        r3 = await dispatch["mysql_execute"]({"query": "DELETE FROM _mcp_test"})
        assert r3.data["affected_rows"] == 2  # type: ignore[index]
    finally:
        await dispatch["mysql_execute"]({"query": "DROP TABLE IF EXISTS _mcp_test"})


# ── Schema ──


@pytest.mark.asyncio
async def test_list_databases(dispatch):
    result = await dispatch["mysql_list_databases"]({})
    assert result.status.value == "success"
    assert len(result.data["databases"]) > 0  # type: ignore[index]


@pytest.mark.asyncio
async def test_list_tables(dispatch):
    result = await dispatch["mysql_list_tables"]({})
    assert result.status.value == "success"
    assert isinstance(result.data["tables"], list)  # type: ignore[index]


@pytest.mark.asyncio
async def test_describe_table(dispatch):
    """创建临时表并查看结构."""
    await dispatch["mysql_execute"]({"query": "CREATE TABLE IF NOT EXISTS _mcp_describe_test (id INT, name VARCHAR(20))"})
    try:
        result = await dispatch["mysql_describe_table"]({"table_name": "_mcp_describe_test"})
        assert result.status.value == "success"
        fields = [r["Field"] for r in result.data["schema"]]  # type: ignore[index]
        assert "id" in fields
        assert "name" in fields
    finally:
        await dispatch["mysql_execute"]({"query": "DROP TABLE IF EXISTS _mcp_describe_test"})
