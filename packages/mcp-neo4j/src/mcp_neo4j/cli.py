"""Neo4j MCP 服务器命令行入口。"""

import asyncio


def main() -> None:
    """MCP 服务器主入口。"""
    from mcp_neo4j.server import Neo4jServer

    server = Neo4jServer()
    asyncio.run(server.run())


if __name__ == "__main__":
    main()
