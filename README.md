# Database CLI workspace

基于 Python 3.10+ 和 uv 构建的 MySQL/Redis/DM 客户端与 JSON 命令行工具。

## 项目结构

```text
./
├── libs/db-cli-kit/         # db-* CLI 共享机制库
├── libs/dm-client/          # 类型化 DM8 执行基础库
├── libs/mysql-client/       # 类型化 MySQL 执行基础库
├── packages/dm-cli/         # db-dm 命令行工具
├── packages/mysql-cli/      # db-mysql 命令行工具
├── packages/redis-cli/      # db-redis 命令行工具
├── Claude.md                # 开发指南
└── pyproject.toml           # 工作区配置
```

## 可用工具

| 包名 | 描述 |
| ---- | ---- |
| [db-cli-kit](libs/db-cli-kit/pyproject.toml) | db-* CLI 共享 JSON、原子持久化、profile 与密钥机制 |
| [dm-client](libs/dm-client/pyproject.toml) | 类型化 DM8 执行基础库 |
| [dm-cli](packages/dm-cli/pyproject.toml) | JSON-only `db-dm` 命令行工具 |
| [mysql-client](libs/mysql-client/pyproject.toml) | 类型化异步 MySQL 执行基础库 |
| [mysql-cli](packages/mysql-cli/pyproject.toml) | JSON-only `db-mysql` 命令行工具 |
| [redis-cli](packages/redis-cli/pyproject.toml) | JSON-first `db-redis` 命令行工具 |

## 快速开始

### 环境要求

- Python 3.10+
- [uv](https://docs.astral.sh/uv/)

### 安装 CLI

```bash
# 在工作区同步依赖
uv sync

# 安装 db-mysql
uv tool install packages/mysql-cli

# 安装 db-redis
uv tool install packages/redis-cli

# 安装 db-dm
uv tool install packages/dm-cli
```

安装后可使用：

```bash
db-redis --json profile list
db-dm --json profile list
```

### 开发模式

```bash
# 安装所有依赖
uv sync

# 运行 CLI 测试
uv run --project packages/mysql-cli pytest
uv run --project packages/redis-cli pytest
uv run --project packages/dm-cli pytest

# 运行客户端测试
uv run --project libs/mysql-client pytest
uv run --project libs/dm-client pytest
uv run --project libs/db-cli-kit pytest libs/db-cli-kit/tests

# 静态检查
uv run ruff check libs/db-cli-kit libs/dm-client packages/dm-cli
uv run python -m mypy libs/db-cli-kit/src libs/dm-client/src packages/dm-cli/src
```

`db-dm` 的 live E2E 测试在设置 `DB_DM_PASSWORD` 后运行；未设置时自动跳过。`sql explain --actual` 的 live 测试还需要 `DB_DM_DBA_PASSWORD` 与 `DB_DM_DISQL_PATH`。

## `db-dm`

`db-dm` 是 DM8 的 JSON-only 命令行工具：

```bash
db-dm --json --profile <profile> sql read --sql "SELECT 1 AS N FROM DUAL"
```

- 成功和失败都只输出一个 JSON document；`--json` 仅用于兼容，输出始终是 JSON。
- `sql explain` 接收原始 SQL，自动去掉一个前导 `EXPLAIN`；不接受参数，且只返回计划文本/节点，不执行 SQL。
- `sql explain --actual` 是可选项：通过 `disql` 的 `SET AUTOTRACE TRACEONLY` 执行只读 SQL，需要设置 `DB_DM_DISQL_PATH`。`plan_text` 仍是估算计划，`statistics` 是实际聚合统计，没有逐算子耗时/循环次数；仅支持 SELECT/WITH，`EXPLAIN ANALYZE` 与写语句会被拒绝。
- DM 使用 `?` 位置参数；`--params-file` 只接受 JSON 数组。`sql read` 默认最多 10,000 行 / 1 MiB。
- `schema analyze` 和 DDL 自动提交；`schema analyze` 没有 `--transaction` 选项。
- 官方 `dmPython` 驱动由 `libs/dm-client` 声明；不需要新增 Docker 镜像或测试 schema，测试表使用 `DB_DM_CLI_TEST_` 前缀。
- 完整命令、JSON envelope 和 profile 字段见 [packages/dm-cli/README.md](packages/dm-cli/README.md)；内部契约见 [docs/dm-cli-contract.md](docs/dm-cli-contract.md)。
- Agent skill： [skills/dm-cli/SKILL.md](skills/dm-cli/SKILL.md)。

MySQL CLI 的命令、SQL 输入和结果约定统一遵循 Codex 全局 `$mysql-cli` Skill；`redis-cli` Skill 安装在 Codex 全局目录。

开发指南和最佳实践请参考 [Claude.md](Claude.md)。

## 许可证

MIT
