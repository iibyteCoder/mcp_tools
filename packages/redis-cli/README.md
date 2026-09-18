# db-redis

面向脚本和 AI agent 的 Redis CLI，完整覆盖当前 `mcp-redis` 的 53 个操作，并支持按命令或在交互模式中切换数据库。

## 安装

```powershell
uv tool install --editable packages/redis-cli
```

连接优先级为：环境默认值、最近的目录绑定、显式 `--profile`、显式连接参数。越靠后优先级越高。

## 使用

```powershell
db-redis --db 2 --json string get --key session:1
db-redis --url redis://localhost:6379/3 key keys --pattern "user:*"
db-redis
```

推荐先通过一个命令保存并绑定当前目录：

```powershell
db-redis --json profile set local-cache --host localhost --port 6379 --password secret --db 2
db-redis --json profile current
db-redis --json server ping
```

在另一个目录执行另一次 `profile set`，同一 `db-redis` 会按所在目录自动选择不同数据库。子目录继承最近的父目录绑定。使用 `profile select NAME` 切换绑定、`profile clear` 解除绑定、`--profile NAME` 临时覆盖。普通结果只附带顶层 `profile` 名称，不重复返回地址、端口等配置。未命名或临时覆盖后与保存配置不一致时为 `null`。用 `profile show NAME` 或 `profile current` 按需查看脱敏详情（位于 `data`）。

配置文件不需要手工编辑。运行 `db-redis --json profile list` 可从 `data.config_file` 查看准确位置；Windows 默认位于 `%APPDATA%\db-cli\connections.json`。该 JSON 只保存非敏感配置，密码由 Windows Credential Manager、macOS Keychain 或 Linux Secret Service 保存。

交互模式中可运行 `use 4` 即时切换逻辑数据库。数组参数可重复传入，例如 `key delete --keys a --keys b`；object 参数传 JSON，例如 `hash hset --mapping '{"name":"Ada"}' --key user:1`。

运行 `db-redis --help` 和各级 `--help` 查看完整命令。

## 修改与校验

`db-redis --json profile set NAME --host new-host --no-bind` 只修改指定字段，保留其他设置和已有目录绑定。全部连接参数见 `profile set --help`。

`db-redis --json profile rename OLD NEW` 保留设置、密码及所有目录绑定，不覆盖已有名称。名称应包含项目和环境，作为智能体识别连接的依据。

保存后先用 `profile show NAME` 核对配置，再执行 `db-redis --profile NAME --json server ping` 校验。保存成功不等于连接成功。已知配置未变化时直接使用名称，无需每次查询详情。

## Agent I/O

`db-redis --json skill path` 返回随工具分发的技能路径，连接配置完整说明位于技能的 `references/connections.md`。

成功且有业务数据时省略重复说明；失败返回 `code` 和必要的 `hint`，包括 JSON 模式的参数错误。写操作超时不能直接重试，应先核实是否已生效。

```powershell
db-redis --profile billing-dev --json key inspect --key session:1 --limit 10 --max-bytes 256
db-redis --profile billing-dev --json key scan --pattern 'session:*' --limit 20
db-redis --profile billing-dev --json server pipeline --commands-file reads.json
```

- `key inspect` returns type, TTL, length and a limited preview for String/Hash/List/Set/Sorted Set. String length is bytes; collection length is items. Preview text is UTF-8 with replacement for cut/invalid bytes. `truncated:true` means more content exists. Hash/set previews are samples; unsupported types return `preview_supported:false`. The byte limit bounds returned text; collection members may be downloaded in full before clipping. Multiple reads are not a snapshot.
- `key scan` returns at most `--limit` keys and a short `next_cursor`. Continue with the same connection and pattern using `--cursor TOKEN`; stop only when `next_cursor` is null, even if a page is empty. Tokens keep unreturned keys in a local cache, expire after 24 hours and cannot move to another machine. SCAN can repeat keys and is not a snapshot; deduplicate for complete inventories. Existing `key keys --page N --page-size N` remains available and defaults to a bounded page.
- `server pipeline` accepts nested JSON arrays. Use `--commands-file FILE` (or `-` for stdin) instead of inline `--commands`; they are mutually exclusive. Results are an ordered array with original JSON types and no command echoes. Database command errors may follow partial effects; never assume a failed write pipeline rolled back.

Prefer exact keys, narrow patterns, bounded ranges and small batches. Repeat options for simple arrays (`--keys a --keys b`); objects use JSON (`--mapping '{"name":"Ada"}'`). Reads can be combined with mget or a small pipeline. `server flushdb` needs explicit authorization to clear the database and `--confirm`.

Groups: `profile`, `connection`, `key`, `string`, `hash`, `list`, `set`, `zset`, `server`, `skill`, `use`.
