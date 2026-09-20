# Redis CLI

`db-redis` 是本项目的 JSON-first Redis 命令行工具。它负责命令参数校验、命名连接 profile、目录绑定和 Redis 操作；密码只进入操作系统凭据管理器，不写入 profile JSON。

## 入口与输出

```bash
uv run --project packages/redis-cli db-redis --json profile list
uv run --project packages/redis-cli db-redis --profile local --json server ping
```

成功输出固定包含 `status`, `profile`, `data`；失败输出固定包含 `status`, `profile`, `error.code`, `error.message`。错误码使用 `ErrorCode` 枚举维护，不能在命令处理器中散落字符串。

## 连接优先级

默认环境变量和默认值 → 当前目录绑定 profile → `--profile` → `--url` → 单项连接参数。使用 `connection status` 可以在不建立连接的情况下检查最终解析结果。

## 命令分组

- `profile`: list/current/show/set/select/bind/clear/rename/remove/validate
- `connection`: status/connect
- `server`: ping/info/dbsize/flushdb/pipeline
- `key`: inspect/scan/keys/delete/exists/type/ttl/expire/persist/rename/random
- `string`, `hash`, `list`, `set`, `zset`: 常用 Redis 数据类型操作
- `skill path`: 输出项目 Skill 文档路径
- `use NAME`: 为当前目录选择一个已保存 profile

破坏性操作必须显式确认，例如 `server flushdb --confirm`。

## 维护约定

- Redis 驱动 API 只能通过 `redis_cli.client.RedisClient` Protocol 进入应用层。
- 跨边界的第三方返回值必须经过 `values.py` 的命名转换函数，禁止把 `Any` 扩散到业务代码。
- 新增可序列化结果时，优先在 `json_types.py` 增加 TypedDict 或数据类，避免匿名结构。
- profile 元数据由 `store.py` 原子写入；secret 由 `secrets.py` 管理；命令层不直接操作文件或 keyring。
