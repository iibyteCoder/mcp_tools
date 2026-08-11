"""Neo4j MCP 工具集成测试 — 需要本地/可访问的 Neo4j 实例."""

import pytest
from conftest import NEO4J_CONFIG  # type: ignore[import-untyped]

from mcp_neo4j.config import Neo4jConfig
from mcp_neo4j.connection import Neo4jConnection
from mcp_neo4j.tools import build_dispatch, get_all_definitions

# ── Fixtures ──


async def _try_connect() -> Neo4jConnection:
    cfg = Neo4jConfig(**NEO4J_CONFIG)
    conn = Neo4jConnection(cfg)
    try:
        await conn.connect()
        return conn
    except Exception as e:
        pytest.skip(f"Neo4j 不可用: {e}")


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
    tools = get_all_definitions()
    assert len(tools) == 9
    names = {t.name for t in tools}
    assert names == {
        "neo4j_connect",
        "neo4j_disconnect",
        "neo4j_status",
        "neo4j_query",
        "neo4j_execute",
        "neo4j_list_labels",
        "neo4j_list_relationship_types",
        "neo4j_list_properties",
        "neo4j_describe_label",
    }


# ── 连接管理 ──


@pytest.mark.asyncio
async def test_status(dispatch):
    result = await dispatch["neo4j_status"]({})
    assert result.status.value == "success"
    assert result.data["connected"] is True  # type: ignore[index]


@pytest.mark.asyncio
async def test_disconnect_reconnect():
    cfg = Neo4jConfig(**NEO4J_CONFIG)
    conn = Neo4jConnection(cfg)
    try:
        await conn.connect()
        assert conn.is_connected
        await conn.disconnect()
        assert not conn.is_connected
        await conn.connect()
        assert conn.is_connected
    except Exception as e:
        pytest.skip(f"Neo4j 不可用: {e}")
    finally:
        await conn.disconnect()


# ── 查询 ──


@pytest.mark.asyncio
async def test_query_return(dispatch):
    result = await dispatch["neo4j_query"]({"query": "RETURN 1 AS num, 'neo4j' AS name"})
    assert result.status.value == "success"
    rows = result.data["rows"]  # type: ignore[index]
    assert len(rows) >= 1
    assert rows[0]["num"] == 1


@pytest.mark.asyncio
async def test_query_pagination(dispatch):
    result = await dispatch["neo4j_query"]({"query": "UNWIND range(1,10) AS n RETURN n", "page": 1, "page_size": 3})
    assert result.status.value == "success"
    assert len(result.data["rows"]) <= 3  # type: ignore[index]
    assert result.data["has_more"] is True  # type: ignore[index]


@pytest.mark.asyncio
async def test_query_with_params(dispatch):
    result = await dispatch["neo4j_query"]({"query": "RETURN $val AS val", "parameters": {"val": 42}})
    assert result.data["rows"][0]["val"] == 42  # type: ignore[index]


@pytest.mark.asyncio
async def test_execute_create_delete(dispatch):
    """测试 CREATE + DELETE 往返."""
    label = "MCPTestNode"
    # 先清理可能残留的测试数据
    await dispatch["neo4j_execute"]({"query": f"MATCH (n:{label}) DELETE n"})

    # CREATE
    r1 = await dispatch["neo4j_execute"]({"query": f"CREATE (a:{label} {{key: 'val1'}}), (b:{label} {{key: 'val2'}})"})
    assert r1.data["nodes_created"] >= 2  # type: ignore[index]

    # 验证
    r2 = await dispatch["neo4j_query"]({"query": f"MATCH (n:{label}) RETURN count(n) AS c"})
    assert r2.data["rows"][0]["c"] >= 2  # type: ignore[index]

    # DELETE
    r3 = await dispatch["neo4j_execute"]({"query": f"MATCH (n:{label}) DELETE n"})
    assert r3.data["nodes_deleted"] >= 2  # type: ignore[index]


# ── Schema ──


@pytest.mark.asyncio
async def test_list_labels(dispatch):
    result = await dispatch["neo4j_list_labels"]({})
    assert result.status.value == "success"
    assert isinstance(result.data["labels"], list)  # type: ignore[index]


@pytest.mark.asyncio
async def test_list_relationship_types(dispatch):
    result = await dispatch["neo4j_list_relationship_types"]({})
    assert result.status.value == "success"
    assert isinstance(result.data["relationship_types"], list)  # type: ignore[index]


@pytest.mark.asyncio
async def test_list_properties(dispatch):
    result = await dispatch["neo4j_list_properties"]({})
    assert result.status.value == "success"
    assert isinstance(result.data["properties"], list)  # type: ignore[index]


@pytest.mark.asyncio
async def test_describe_label_invalid(dispatch):
    """Cypher 查询中对不存在的标签会产生语法错误, 验证不会崩溃."""
    import neo4j

    try:
        result = await dispatch["neo4j_describe_label"]({"label": "_NonexistentMCPTestLabel"})
        # handler 直接返回错误
        assert result.status.value == "error"
    except neo4j.exceptions.Neo4jError:
        # 直接抛异常也是合理行为 (会被 BaseMCPServer._call_tool_wrapper 捕获并转为 ToolResult.error)
        pass
