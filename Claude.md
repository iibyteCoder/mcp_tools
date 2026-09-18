# MySQL CLI

> 本文件精简编写，仅保留项目特定约定，不写 AI 已知的基础知识。

## 架构

Monorepo 结构，客户端库和命令行工具分别维护。

```
./
├── libs/mysql-client/      # 类型化 MySQL 执行基础库
├── packages/mysql-cli/       # db-mysql 命令行工具
├── skills/mysql-cli/       # CLI 使用契约
└── pyproject.toml          # workspace 配置
```

## 核心约定

1. **边界清晰** - `mysql-client` 负责协议、解析、策略和执行；`mysql-cli` 负责 CLI 输入输出与 profile 管理
2. **异步优先** - MySQL I/O 使用 `async/await`，驱动细节隔离在 `mysql_client.adapters.aiomysql`
3. **类型注解** - Python 3.10+ 语法 (`X | None` 而非 `Optional[X]`)
4. **JSON 契约** - CLI 成功和失败输出都保持机器可读，命令入口使用 `db-mysql`

## 开发与验证

```bash
# 同步依赖
uv sync

# CLI 测试
uv run --project packages/mysql-cli pytest

# 客户端测试
uv run --project libs/mysql-client pytest

# 静态检查
uv run ruff check libs/mysql-client packages/mysql-cli
uv run mypy libs/mysql-client/src packages/mysql-cli/src
```
