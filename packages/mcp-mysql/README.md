# MCP MySQL 服务器

基于 MCP 协议的 MySQL 数据库操作服务器，支持异步查询和连接池。

## 安装

### 全局安装

```bash
cd packages/mcp-mysql
uv tool install .
```

安装后可直接运行：

```bash
mcp-mysql
```

### 使用 uvx 运行（无需安装）

```bash
uvx --from /path/to/packages/mcp-mysql mcp-mysql
```

## 配置

支持环境变量或 `.env` 文件配置：

```bash
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=your_password
MYSQL_DATABASE=your_database
MYSQL_CHARSET=utf8mb4
MYSQL_CONNECTION_TIMEOUT=10
```

## 可用工具

| 工具 | 说明 |
| ---- | ---- |
| `mysql_connect` | 连接到 MySQL 数据库，支持自定义连接参数 |
| `mysql_disconnect` | 断开当前数据库连接 |
| `mysql_query` | 执行 SELECT 查询，返回结果集 |
| `mysql_execute` | 执行 INSERT/UPDATE/DELETE 语句，返回影响行数 |
| `mysql_list_databases` | 列出服务器上所有数据库 |
| `mysql_list_tables` | 列出当前数据库中的所有表 |
| `mysql_describe_table` | 获取指定表的结构信息 |

## 在 Claude Desktop 中使用

添加到 Claude Desktop 配置文件：

```json
{
  "mcpServers": {
    "mysql": {
      "command": "mcp-mysql",
      "env": {
        "MYSQL_HOST": "localhost",
        "MYSQL_USER": "root",
        "MYSQL_PASSWORD": "your_password",
        "MYSQL_DATABASE": "your_database"
      }
    }
  }
}
```

## 技术特性

- 基于 `aiomysql` 实现异步数据库操作
- 使用连接池管理数据库连接
- 支持参数化查询，防止 SQL 注入
- 自动重连机制
