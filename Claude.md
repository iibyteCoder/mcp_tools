# Database CLI

> 本文件精简编写，仅保留项目特定约定，不写 AI 已知的基础知识。

## 架构

Monorepo 结构，客户端库和命令行工具分别维护。

```
./
├── libs/db-cli-kit/        # db-* CLI 共享机制库
├── libs/dm-client/         # 类型化 DM8 执行基础库
├── libs/mysql-client/      # 类型化 MySQL 执行基础库
├── packages/dm-cli/        # db-dm 命令行工具
├── packages/mysql-cli/     # db-mysql 命令行工具
├── packages/redis-cli/     # db-redis 命令行工具
└── pyproject.toml          # workspace 配置
```

## 核心约定

1. **边界清晰** - `mysql-client` 负责协议、解析、策略和执行；`mysql-cli` 负责 CLI 输入输出与 profile 管理
2. **异步优先** - MySQL I/O 使用 `async/await`，驱动细节隔离在 `mysql_client.adapters.aiomysql`
3. **类型注解** - Python 3.10+ 语法 (`X | None` 而非 `Optional[X]`)
4. **MySQL CLI 指引** - 命令、SQL 输入、安全约束和输出契约统一遵循 Codex 全局 `$mysql-cli` Skill
5. **Redis 分层** - `redis-cli` 按 domain、store/secrets、client、application、rendering 和 Click presentation 分层；Redis 驱动只允许通过 `RedisClient` Protocol 进入应用层
6. **严格类型** - 对外结果使用 TypedDict 或数据类，第三方返回值在边界转换；不使用 `Any` 或未命名的业务结果结构
7. **DM 分层** - `dm-client` 负责 DM 协议、解析、策略和执行；`dm-cli` 负责 CLI 输入输出与 profile 管理；`db-cli-kit` 只提供 DB 无关的 JSON、原子持久化、profile 名和密钥机制
8. **单向依赖** - `db-cli-kit` 不依赖任何数据库驱动或 Click；`dm-client` 不依赖 `dm-cli`、Click、keyring；`dm-cli.application` 不依赖 Click 或 adapters；只有 `composition.py` 构造 adapter；`dmPython` 只允许出现在 `dm_client.adapters.dmpython`
9. **DM 参数与事务** - dmPython 只支持 `?` 位置参数（`--params-file` 只接受 JSON 数组）；DDL 自动提交，`schema analyze` 的 DBMS_STATS 也按自动提交处理且不提供 `--transaction`
10. **DM CLI 契约** - 命令树、JSON envelope、错误码、结果结构和 DM 特性统一遵循 [docs/dm-cli-contract.md](docs/dm-cli-contract.md)

## 开发与验证

```bash
# 同步依赖
uv sync

# CLI 测试
uv run --project packages/mysql-cli pytest
uv run --project packages/redis-cli pytest
uv run --project packages/dm-cli pytest

# 客户端测试
uv run --project libs/mysql-client pytest
uv run --project libs/dm-client pytest
uv run --project libs/db-cli-kit pytest libs/db-cli-kit/tests

# 静态检查
uv run ruff check libs/mysql-client packages/mysql-cli
uv run ruff check packages/redis-cli/src
uv run ruff check libs/db-cli-kit libs/dm-client packages/dm-cli
uv run python -m mypy libs/mysql-client/src packages/mysql-cli/src packages/redis-cli/src
uv run python -m mypy libs/db-cli-kit/src libs/dm-client/src packages/dm-cli/src
```

`db-dm` 的 live E2E 测试需要环境变量 `DB_DM_PASSWORD`；未设置时自动跳过，且不得把密码写入仓库或 profile 文件。

## db-dm 速览

```text
profile  list/show/set/validate/bind/unbind/rename/remove
server   inspect/capabilities/parameters
schema   databases/tables/describe/indexes/stats/ddl/constraints/objects/analyze
sql      read/write/explain/benchmark/compare
sql      explain --actual   # 可选：disql AUTOTRACE TRACEONLY
```

- 输出始终是单个 JSON document；`--json` 只是兼容选项。
- `sql explain` 接受原始 SQL 并剥离一个前导 `EXPLAIN`，不接受参数，且默认不执行被解释的 SQL。
- `sql explain --actual` 通过 `disql` 的 `SET AUTOTRACE TRACEONLY` 执行只读 SQL，需要 `DB_DM_DISQL_PATH`；`plan_text` 为估算计划，`statistics` 为实际聚合统计，无逐算子耗时/循环次数，仅支持 SELECT/WITH。
- `sql read` 和 `sql compare` 每侧默认 10,000 行 / 1 MiB；`sql benchmark` 默认 5 次计时 + 1 次 warmup，上限 100/10。
- live E2E 测试表使用 `DB_DM_CLI_TEST_` 前缀并在 `finally` 中清理；不需要新增 Docker 镜像或测试 schema。
- 完整契约见 [docs/dm-cli-contract.md](docs/dm-cli-contract.md)，用户文档见 [packages/dm-cli/README.md](packages/dm-cli/README.md)。
- Agent skill 见 [skills/dm-cli/SKILL.md](skills/dm-cli/SKILL.md)。
