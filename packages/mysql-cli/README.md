# db-mysql

面向脚本和 AI agent 的 MySQL CLI，完整覆盖当前 `mcp-mysql` 的 8 个操作，并支持按命令或在交互模式中切换数据库。

## 安装

```powershell
uv tool install --editable packages/mysql-cli
```

连接优先级为：环境默认值、最近的目录绑定、显式 `--profile`、显式连接参数。越靠后优先级越高。

## 使用

```powershell
db-mysql --database app --json sql query --query "SELECT * FROM users" --page-size 20
db-mysql --url mysql://root:password@localhost:3306/app schema tables
db-mysql
```

推荐先通过一个命令保存并绑定当前目录：

```powershell
db-mysql --json profile set local-app --host localhost --port 3306 --user root --password secret --database app
db-mysql --json profile current
db-mysql --json schema tables
```

在另一个目录执行另一次 `profile set`，同一 `db-mysql` 会按所在目录自动选择不同数据库。子目录继承最近的父目录绑定。使用 `profile select NAME` 切换绑定、`profile clear` 解除绑定、`--profile NAME` 临时覆盖。普通结果只附带顶层 `profile` 名称，不重复返回地址、端口等配置。未命名或临时覆盖后与保存配置不一致时为 `null`。用 `profile show NAME` 或 `profile current` 按需查看脱敏详情（位于 `data`）。

配置文件不需要手工编辑。运行 `db-mysql --json profile list` 可从 `data.config_file` 查看准确位置；Windows 默认位于 `%APPDATA%\db-cli\connections.json`。该 JSON 只保存非敏感配置，密码由 Windows Credential Manager、macOS Keychain 或 Linux Secret Service 保存。

交互模式中可运行 `use analytics` 即时重建连接池并切换数据库。运行 `db-mysql --help` 和各级 `--help` 查看完整命令。

`sql query` 用于 SELECT 并提供分页；`sql execute` 用于 INSERT、UPDATE、DELETE 和 DDL。

## 修改与校验

`db-mysql --json profile set NAME --host new-host --no-bind` 只修改指定字段，保留其他设置和已有目录绑定。全部连接参数见 `profile set --help`。

`db-mysql --json profile rename OLD NEW` 保留设置、密码及所有目录绑定，不覆盖已有名称。名称应包含项目和环境，作为智能体识别连接的依据。

保存后先用 `profile show NAME` 核对配置，再执行 `db-mysql --profile NAME --json sql query --query "SELECT 1 AS ok, DATABASE() AS db"` 校验。保存成功不等于连接成功。已知配置未变化时直接使用名称，无需每次查询详情。

## Agent I/O

`db-mysql --json skill path` 返回随工具分发的技能路径，连接配置完整说明位于技能的 `references/connections.md`。

成功且有业务数据时省略重复说明；失败返回 `code` 和必要的 `hint`，包括 JSON 模式的参数错误。写操作超时不能直接重试，应先核实是否已生效。

```powershell
db-mysql --profile billing-dev --json schema describe --table-name invoices
db-mysql --profile billing-dev --json sql query --query "SELECT id, total FROM invoices ORDER BY id" --page 1 --page-size 20
db-mysql --profile billing-dev --json sql query --query-file query.sql
```

`sql query` reads SELECT results; `sql execute` performs authorized writes/DDL and supports `--query-file` too. Inline `--query` and `--query-file` are mutually exclusive; file `-` reads stdin as text. Files are UTF-8. Prefer files for long SQL or difficult shell quoting.

Inspect only relevant schema; select needed columns and filter rows. Follow `data.next_page` only if additional rows are needed and `data.has_more` is true. Write output contains affected counts/IDs without echoing SQL. Verify affected scope when appropriate.

Groups: `profile`, `connection`, `schema`, `sql`, `skill`, `use`.
