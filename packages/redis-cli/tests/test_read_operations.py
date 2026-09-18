from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_scan_continuation_preserves_oversized_batch(tmp_path):
    from redis_cli.read_operations import scan_page

    client = AsyncMock()
    client.scan.side_effect = [(7, ["a", "b", "c", "d"]), (0, ["e"])]
    first = await scan_page(client, "*", 2, None, "target", tmp_path)
    second = await scan_page(client, "*", 2, first["next_cursor"], "target", tmp_path)
    third = await scan_page(client, "*", 2, second["next_cursor"], "target", tmp_path)
    assert first["keys"] + second["keys"] + third["keys"] == ["a", "b", "c", "d", "e"]
    assert third["next_cursor"] is None
    assert client.scan.call_count == 2
    assert len(first["next_cursor"]) < 100


@pytest.mark.asyncio
async def test_cursor_is_bound_to_connection_and_pattern(tmp_path):
    from redis_cli.read_operations import scan_page

    client = AsyncMock()
    client.scan.return_value = (7, ["a", "b"])
    first = await scan_page(client, "a*", 1, None, "one", tmp_path)
    with pytest.raises(ValueError):
        await scan_page(client, "a*", 1, first["next_cursor"], "two", tmp_path)
    with pytest.raises(ValueError):
        await scan_page(client, "b*", 1, first["next_cursor"], "one", tmp_path)


@pytest.mark.asyncio
async def test_empty_scan_batch_returns_continuation_without_looping(tmp_path):
    from redis_cli.read_operations import scan_page

    client = AsyncMock()
    client.scan.return_value = (3, [])
    result = await scan_page(client, "rare*", 2, None, "one", tmp_path)
    assert result["keys"] == []
    assert result["next_cursor"]
    assert client.scan.call_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("token", ["../escape", "invalid", "0" * 32])
async def test_invalid_cursor_does_not_call_server(tmp_path, token):
    from redis_cli.read_operations import scan_page

    client = AsyncMock()
    with pytest.raises(ValueError):
        await scan_page(client, "*", 2, token, "one", tmp_path)
    client.scan.assert_not_called()


@pytest.mark.asyncio
async def test_inspect_string_is_bounded():
    from redis_cli.read_operations import inspect_key

    client = AsyncMock()
    client.type.return_value = "string"
    client.ttl.return_value = 30
    client.strlen.return_value = 10000
    client.execute_command.return_value = b"abcde"
    result = await inspect_key(client, "key", 3, 5)
    assert result == {"type": "string", "ttl": 30, "length": 10000, "preview": "abcde", "truncated": True}
    client.execute_command.assert_awaited_once_with("GETRANGE", "key", 0, 4, NEVER_DECODE=True)
    client.get.assert_not_called()


@pytest.mark.asyncio
async def test_inspect_missing_key():
    from redis_cli.read_operations import inspect_key

    client = AsyncMock()
    client.type.return_value = "none"
    assert await inspect_key(client, "missing", 3, 5) == {"type": "none", "ttl": -2}


@pytest.mark.asyncio
async def test_inspect_list_has_item_and_text_limits():
    from redis_cli.read_operations import inspect_key

    client = AsyncMock()
    client.type.return_value = "list"
    client.ttl.return_value = -1
    client.llen.return_value = 4
    client.lrange.return_value = ["long-value", "b"]
    result = await inspect_key(client, "key", 2, 4)
    assert result["preview"] == ["long", "b"]
    assert result["truncated"] is True
    client.lrange.assert_awaited_once_with("key", 0, 1)
