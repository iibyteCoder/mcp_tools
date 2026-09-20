# Database CLI

> 本文件精简编写，仅保留项目特定约定，不写 AI 已知的基础知识。

## 架构

Monorepo 结构，客户端库和命令行工具分别维护。

```
./
├── libs/mysql-client/      # 类型化 MySQL 执行基础库
├── packages/mysql-cli/       # db-mysql 命令行工具
├── packages/redis-cli/     # db-redis 命令行工具
├── skills/mysql-cli/       # MySQL CLI 使用契约
├── skills/redis-cli/       # Redis CLI 使用契约
└── pyproject.toml          # workspace 配置
```

## 核心约定

1. **边界清晰** - `mysql-client` 负责协议、解析、策略和执行；`mysql-cli` 负责 CLI 输入输出与 profile 管理
2. **异步优先** - MySQL I/O 使用 `async/await`，驱动细节隔离在 `mysql_client.adapters.aiomysql`
3. **类型注解** - Python 3.10+ 语法 (`X | None` 而非 `Optional[X]`)
4. **JSON 契约** - CLI 成功和失败输出都保持机器可读，命令入口使用 `db-mysql`
5. **Redis 分层** - `redis-cli` 按 domain、store/secrets、client、application、rendering 和 Click presentation 分层；Redis 驱动只允许通过 `RedisClient` Protocol 进入应用层
6. **严格类型** - 对外结果使用 TypedDict 或数据类，第三方返回值在边界转换；不使用 `Any` 或未命名的业务结果结构

## 开发与验证

```bash
# 同步依赖
uv sync

# CLI 测试
uv run --project packages/mysql-cli pytest
uv run --project packages/redis-cli pytest

# 客户端测试
uv run --project libs/mysql-client pytest

# 静态检查
uv run ruff check libs/mysql-client packages/mysql-cli
uv run ruff check packages/redis-cli/src
uv run python -m mypy libs/mysql-client/src packages/mysql-cli/src packages/redis-cli/src
```
