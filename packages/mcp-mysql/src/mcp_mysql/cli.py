"""CLI entry point for MySQL MCP server."""

import asyncio


def main() -> None:
    """Main entry point for the MCP server."""
    from mcp_mysql.server import MySQLServer

    server = MySQLServer()
    asyncio.run(server.run())


if __name__ == "__main__":
    main()
