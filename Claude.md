# MCP Tools

> 本文件精简编写，仅保留项目特定约定，不写 AI 已知的基础知识。

## 架构

Monorepo 结构，每个 MCP 服务是独立可安装的 Python 包。

```
mcp_tools/
├── packages/      # 独立服务 (mcp-mysql, mcp-redis, ...)
├── libs/mcp-base/ # 共享基类 (BaseMCPServer, BaseConfig, ToolResult)
└── pyproject.toml # workspace 配置
```

## 核心约定

1. **异步优先** - 所有 I/O 使用 `async/await`，数据库用连接池
2. **模块分离** - `cli.py` | `server.py` | `config.py` | `connection.py` | `tools.py`
3. **类型注解** - Python 3.10+ 语法 (`X | None` 而非 `Optional[X]`)
4. **命名** - 包名 `mcp_xxx`，工具名 `xxx_action`，类名 `PascalCase`

## 添加新服务

```bash
mkdir -p packages/mcp-xxx/src/mcp_xxx
```

```toml
# packages/mcp-xxx/pyproject.toml
[project]
name = "mcp-xxx"
dependencies = ["mcp-base", "<async-driver>"]

[project.scripts]
mcp-xxx = "mcp_xxx.cli:main"

[tool.uv.sources]
mcp-base = { workspace = true }
```

```python
# src/mcp_xxx/server.py
from mcp_base.server import BaseMCPServer

class XxxServer(BaseMCPServer):
    async def list_tools(self) -> list[Tool]: ...
    async def call_tool(self, name: str, args: dict) -> ToolResult: ...
```

## 使用

```bash
# 开发
uv sync && uv run mcp-mysql

# 全局安装
cd packages/mcp-mysql && uv tool install .
```
