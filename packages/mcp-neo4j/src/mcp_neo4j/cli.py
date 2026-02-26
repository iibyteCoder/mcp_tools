"""CLI entry point for Neo4j MCP server."""

import asyncio


def main() -> None:
    """Main entry point for the MCP server."""
    from mcp_neo4j.server import Neo4jServer

    server = Neo4jServer()
    asyncio.run(server.run())


if __name__ == "__main__":
    main()
