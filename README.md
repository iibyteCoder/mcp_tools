# MCP Tools

基于 Python 3.10+ 和 uv 构建的 MCP（Model Context Protocol）服务器集合。

## 项目结构

```text
mcp_tools/
├── packages/           # 独立的 MCP 服务包
│   ├── mcp-mysql/     # MySQL MCP 服务器
│   ├── mcp-neo4j/     # Neo4j MCP 服务器
│   ├── mysql-cli/     # MySQL 命令行客户端
│   └── redis-cli/     # Redis 命令行客户端
├── libs/               # 共享库
│   ├── mcp-base/      # MCP 基类和工具函数
│   └── db-cli-core/   # 数据库 CLI 共享命令框架
├── Claude.md           # 开发指南
└── pyproject.toml      # 工作区配置
```

## 可用服务

| 包名 | 描述 | 状态 |
| ---- | ---- | ---- |
| [mcp-mysql](packages/mcp-mysql/README.md) | MySQL 数据库操作 | 已就绪 |
| [mcp-neo4j](packages/mcp-neo4j/README.md) | Neo4j 图数据库操作 | 已就绪 |
| [db-redis](packages/redis-cli/README.md) | Redis CLI 与交互式切库 | 已就绪 |
| [db-mysql](packages/mysql-cli/README.md) | MySQL CLI 与交互式切库 | 已就绪 |

## 快速开始

### 环境要求

- Python 3.10+
- [uv](https://docs.astral.sh/uv/)

### 全局安装服务

```bash
# 安装 MySQL MCP 服务器
cd packages/mcp-mysql
uv tool install .

# 安装 Neo4j MCP 服务器
cd packages/mcp-neo4j
uv tool install .

# 安装后可全局使用
mcp-mysql
mcp-neo4j
```

### 使用 uvx 运行（无需安装）

```bash
uvx --from /path/to/packages/mcp-mysql mcp-mysql
```

### 开发模式

```bash
# 安装所有依赖
uv sync

# 开发模式下运行服务
uv run mcp-mysql
```

### 数据库 CLI

```bash
uv sync --all-packages
uv run db-redis --db 2 --json server ping
uv run db-mysql --database app --json schema tables
```

不带子命令运行 `uv run db-redis` 或 `uv run db-mysql` 可进入持续连接的交互模式，使用 `use` 切换数据库。

连接可以完全通过 CLI 配置并按目录自动选择：

```powershell
db-mysql --json profile set app-db --host localhost --user root --password secret --database app
db-redis --json profile set app-cache --host localhost --db 2

# 此目录及其子目录后续无需再传连接参数
db-mysql --json schema tables
db-redis --json server ping
```

`profile current` 查看当前目录实际选中的连接，`profile select NAME` 切换目录绑定。每个命令的 JSON 返回都带有脱敏的顶层 `connection` 字段。配置由命令原子写入用户配置目录；`--json profile list` 的 `data.config_file` 会返回当前机器上的准确位置。密码由操作系统凭据库保存，不写入连接配置 JSON。

## 添加新服务

开发指南和最佳实践请参考 [Claude.md](Claude.md)。

## 许可证

MIT
