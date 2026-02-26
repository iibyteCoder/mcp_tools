# MCP MySQL Server

MCP (Model Context Protocol) server for MySQL database operations.

## Installation

### Global installation with uv

```bash
cd packages/mcp-mysql
uv tool install .
```

### Run with uvx (no installation)

```bash
uvx --from /path/to/packages/mcp-mysql mcp-mysql
```

## Configuration

Set environment variables or create a `.env` file:

```bash
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=your_password
MYSQL_DATABASE=your_database
```

## Available Tools

| Tool | Description |
|------|-------------|
| `mysql_connect` | Connect to MySQL database |
| `mysql_disconnect` | Disconnect from database |
| `mysql_query` | Execute SELECT queries |
| `mysql_execute` | Execute INSERT/UPDATE/DELETE |
| `mysql_list_databases` | List all databases |
| `mysql_list_tables` | List tables in current database |
| `mysql_describe_table` | Get table schema |

## Usage with Claude Desktop

Add to your Claude Desktop config:

```json
{
  "mcpServers": {
    "mysql": {
      "command": "mcp-mysql",
      "env": {
        "MYSQL_HOST": "localhost",
        "MYSQL_USER": "root",
        "MYSQL_PASSWORD": "your_password"
      }
    }
  }
}
```
