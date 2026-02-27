# MCP Tools

基于 Python 3.10+ 和 uv 构建的 MCP（Model Context Protocol）服务器集合。

## 项目结构

```text
mcp_tools/
├── packages/           # 独立的 MCP 服务包
│   ├── mcp-mysql/     # MySQL MCP 服务器
│   └── mcp-neo4j/     # Neo4j MCP 服务器
├── libs/               # 共享库
│   └── mcp-base/      # 基类和工具函数
├── Claude.md           # 开发指南
└── pyproject.toml      # 工作区配置
```

## 可用服务

| 包名 | 描述 | 状态 |
| ---- | ---- | ---- |
| [mcp-mysql](packages/mcp-mysql/README.md) | MySQL 数据库操作 | 已就绪 |
| [mcp-neo4j](packages/mcp-neo4j/README.md) | Neo4j 图数据库操作 | 已就绪 |

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

## 添加新服务

开发指南和最佳实践请参考 [Claude.md](Claude.md)。

## 许可证

MIT
