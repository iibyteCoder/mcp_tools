"""Redis MCP 服务器命令行入口."""

import asyncio


def main() -> None:
    """MCP 服务器主入口."""
    from mcp_redis.server import RedisServer

    server = RedisServer()
    asyncio.run(server.run())


if __name__ == "__main__":
    main()
