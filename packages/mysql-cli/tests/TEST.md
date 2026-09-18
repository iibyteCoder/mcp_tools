# MySQL CLI Test Plan

## Inventory

- `test_config.py`: URL、覆盖优先级、密码遮蔽和空数据库
- `test_catalog.py`: 8 个枚举命令与 MCP schema 一一对应
- `test_backend.py`: 延迟连接、分发、切库和关闭生命周期
- `test_cli.py`: help、JSON、SQL 参数和错误退出码
- `test_cli.py`: 命令创建连接配置、目录绑定、无参数自动选择和当前连接回显
- `test_e2e.py`: 真实 MySQL 的建表、写入、分页、schema 与清理工作流

## Real workflows

- 列出数据库、切换目标、列出表，验证当前数据库。
- 创建临时表并执行 insert/select/update/delete/drop，验证真实提交结果。
- 分页读取多行数据，验证页边界与 `has_more`。
- describe 临时表，验证字段名与 MySQL 类型。
- 使用安装后的 `db-mysql` 命令执行 `--help` 和 JSON 往返。
- 在两个目录绑定不同命名连接，验证同一命令按工作目录自动选择且互不覆盖。

## Results

2026-08-18 验证结果：

```text
$ DB_CLI_FORCE_INSTALLED=1 uv run pytest -v --tb=no
collected 80 items
packages/mysql-cli/tests: 11 passed
full workspace: 80 passed in 49.12s
```

真实 MySQL 验证使用测试配置调用安装后的 `db-mysql`，完成 `use` 切库并执行 `SELECT 1 AS ok`，随后解析 JSON 验证数据库名与行内容。

覆盖缺口：CLI-specific E2E 未重复 MCP 套件已有的写入/DDL 往返；全仓 `tests/test_mysql.py` 已覆盖 create/insert/select/delete/drop。

## 2026-09-04 efficiency test plan

- Shared tests: compact success, typed errors including chained authentication errors, JSON parser errors, file/stdin input and conflicts, installed skill discovery (about 15 cases).
- Redis extension tests: bounded type-specific inspection, absent keys, lossless continuation across oversized/empty SCAN batches, invalid continuation tokens (about 8 cases).
- Installed CLI checks: malformed arguments, skill/reference paths, MySQL read via input file, Redis typed pipeline and inspection/scan on unique test keys in DB 14; clean only keys created by this run.

## 2026-09-04 verified results

Command: `DB_CLI_FORCE_INSTALLED=1 uv run --no-sync --all-packages pytest libs/db-cli-core/tests packages/mysql-cli/tests packages/redis-cli/tests -v --tb=short`

Result: **92 passed in 23.36s**, no skips. Includes installed skill-path/JSON parser checks, UTF-8 SQL file query against MySQL, Redis DB 14/15 isolation, typed pipeline results and bounded inspect/SCAN on unique test keys. Test-created keys were cleaned up. MySQL checks were read-only.

Static validation: mypy passed for 39 source files; Ruff check/format passed; both skills passed quick_validate. Both wheel packages were built and inspected for SKILL.md and references/connections.md.

Limits: tests do not establish all production permissions or a Redis snapshot guarantee. Redis cursor tokens are local and expire after 24 hours; old cached pages are cleaned on subsequent scan starts. Collection preview byte limits bound output, not total network data for large members. Nonfinite numeric scores are represented by JSON strings. Writes are never automatically retried after uncertain outcomes.
