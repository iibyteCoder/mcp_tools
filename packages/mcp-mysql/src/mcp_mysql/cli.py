"""MySQL MCP 服务器命令行入口。"""

import asyncio


def main() -> None:
    """MCP 服务器主入口。"""
    from mcp_mysql.server import MySQLServer

    server = MySQLServer()
    asyncio.run(server.run())


if __name__ == "__main__":
    main()
