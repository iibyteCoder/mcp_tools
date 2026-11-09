---
name: mysql-cli
description: Use when the user asks to inspect or operate MySQL with "db-mysql", run or explain MySQL SQL, benchmark or compare queries, inspect schemas/indexes/statistics, analyze table statistics, inspect server variables/status/processes, or manage MySQL connection profiles.
---

# MySQL CLI

`db-mysql` is the JSON-only command-line tool for MySQL. Prefer one-shot calls
with `--json`. Every command writes exactly one JSON document to stdout; `help`
and `--version` are intentionally human-readable exceptions. A non-zero exit
status or `ok:false` means failure.

## Command tree

```text
help
--version

profile list|show|set|validate|bind|unbind|rename|remove
server inspect|capabilities|variables|status|processes
schema databases|tables|describe|indexes|stats|analyze
sql read|write|explain|benchmark|compare
```

Examples:

```powershell
db-mysql --json profile list
db-mysql --json --profile billing-dev server inspect
db-mysql --json --profile billing-dev server capabilities
db-mysql --json --profile billing-dev server variables --filter innodb
db-mysql --json --profile billing-dev server status --filter threads
db-mysql --json --profile billing-dev server processes
db-mysql --json --profile billing-dev server processes --include-sql

db-mysql --json --profile billing-dev schema databases
db-mysql --json --profile billing-dev schema tables --database billing
db-mysql --json --profile billing-dev schema describe --table invoices
db-mysql --json --profile billing-dev schema indexes --table invoices
db-mysql --json --profile billing-dev schema stats --table invoices
db-mysql --json --profile billing-dev schema analyze --table invoices --database billing

db-mysql --json --profile billing-dev sql read --sql "SELECT id FROM invoices"
db-mysql --json --profile billing-dev sql explain --sql "EXPLAIN SELECT id FROM invoices"
db-mysql --json --profile billing-dev sql explain --sql "EXPLAIN FORMAT=JSON SELECT id FROM invoices"
db-mysql --json --profile billing-dev sql explain --analyze --sql "SELECT id FROM invoices WHERE id = 1"
db-mysql --json --profile billing-dev sql benchmark --sql "SELECT id FROM invoices" --iterations 10
db-mysql --json --profile billing-dev sql compare --left-sql-file old.sql --right-sql-file new.sql --key-column id
```

- Run `db-mysql help` for the group list and `db-mysql <group> --help` for leaves.
- `--json` is accepted for compatibility; output is always JSON.

## Profiles and connections

Read [references/connections.md](references/connections.md) for profile fields,
directory binding, keyring behavior, and validation.

A profile stores `host`, `port`, `user`, optional `database`, `charset`,
`connect_timeout`, and `read_timeout`. Passwords go to the OS credential manager
under keyring service `db-mysql`; they are never stored in profile JSON. Use
`profile show` to inspect non-secret settings and `profile validate` to open a
real connection.

Select a profile with `--profile`, or bind one to a directory with `profile bind`.
Without a profile or binding, SQL commands produce local parse diagnostics only;
they do not connect. Never silently switch to another profile or database.

## Server and schema inspection

`server` and `schema` inspection commands are read-only unless noted.

- `server inspect` reports version, host, port, current database/user and
  character-set/collation facts.
- `server capabilities` reports version, isolation, autocommit,
  `performance_schema`, SSL and `sql_mode`.
- `server variables [--filter TEXT | --all]` reads
  `performance_schema.global_variables`; without flags it returns a curated
  performance-relevant subset. Sensitive variable values are `NULL` with
  `redacted=1`.
- `server status [--filter TEXT | --all]` reads
  `performance_schema.global_status`; values are MySQL strings, not coerced
  integers.
- `server processes [--include-sql]` reads `performance_schema.processlist`.
  `info` is `NULL` by default so SQL text/credentials do not leak;
  `--include-sql` explicitly opts in and may expose sensitive SQL.
- Variable/status/process visibility follows MySQL privileges. Without
  `PROCESS`, the server may return only the current user's threads; the CLI
  never escalates privileges.
- These commands require MySQL 8 with `performance_schema` available. There is
  no information_schema/SHOW fallback; a disabled performance_schema surfaces
  as a normal typed execution error.

Schema inspection results use the existing `InspectionResult` shape:
`data.result.query` contains `columns`, `rows`, `truncated`, and `metadata`.

- `schema databases` lists visible databases.
- `schema tables` lists tables with engine and estimated row count.
- `schema describe` adds column type, nullability, default, extra and comments.
- `schema indexes` reports index name, uniqueness, column order, cardinality,
  prefix length and index type.
- `schema stats` reports engine, estimated rows, data/index/free sizes and update
  time.

`schema analyze --table T [--database D] [--timeout SEC]` executes
`ANALYZE TABLE`; it is **not** read-only, may take metadata locks, and has no
`--transaction` option. It returns typed `Table/Op/Msg_type/Msg_text` facts.

## SQL input and intent

`sql read`, `sql write`, `sql explain`, and `sql benchmark` accept:

- `--sql TEXT`
- `--sql-file PATH`; `--sql-file -` reads stdin
- `--params-file PATH`

`--sql` and `--sql-file` are mutually exclusive. SQL files are UTF-8. Each
invocation accepts exactly one statement. The CLI validates and classifies the
statement before execution; it never wraps SQL, adds pagination, or rewrites the
statement.

MySQL uses `%s` parameters. `--params-file` is a top-level JSON array:

```json
[42, "alpha"]
```

The requested command must match the statement classification: `read` for
SELECT/SHOW/DESCRIBE, `write` for INSERT/UPDATE/DELETE/DDL, `explain` for
EXPLAIN/EXPLAIN ANALYZE, and `benchmark`/`compare` for reads.

`sql read` defaults to at most 10,000 rows / 1 MiB per result. Use `--max-rows` /
`--max-bytes` to change the bounds; `truncated=true` means a bound was hit.
`sql write` commits by default; `--transaction rollback` rolls back explicitly.

## Explain

Normal `sql explain` sends one supplied `EXPLAIN` statement exactly as written,
including `EXPLAIN ANALYZE` and `FORMAT=JSON/TREE`; it does not prepend or wrap
SQL. The result reports the detected `format`; `EXPLAIN ANALYZE` is `TREE`.

```powershell
# Estimated plan
db-mysql --json --profile billing-dev sql explain `
  --sql "EXPLAIN SELECT * FROM invoices WHERE id = 1"

# Actual execution plan; executes the query (MySQL 8.0.18+)
db-mysql --json --profile billing-dev sql explain --analyze `
  --sql "SELECT * FROM invoices WHERE id = 1"
```

- `--analyze` accepts only raw SELECT/WITH; do not include `EXPLAIN`.
- It executes the query through `EXPLAIN ANALYZE`; only read-only statements are
  accepted.
- `EXPLAIN ANALYZE` supports TREE output; non-TREE `ANALYZE` formats and unknown
  `FORMAT` values return `unsupported_sql`.
- `--params-file` remains available on normal explain and `--analyze`.

## Benchmark and compare

- `sql benchmark` is read-only. Defaults: 5 timed iterations + 1 warmup, maximum
  100 / 10; returns samples and min/max/average/median milliseconds.
- `sql compare` executes both sides once and compares columns and rows. Repeat
  `--key-column` for keyed comparison; otherwise rows compare positionally.
  Equal results return `equal=true`; unequal results return `comparison_failed`
  (exit 5) with `error.differences`. It compares result sets, not plans.

## Output and errors

Success envelopes are `ok` + `data` + `meta`; failures are `ok` + `error` +
`meta`. Errors contain a stable `error.code`; never echo passwords, keyring
values, sensitive variable values, or SQL text unless the command explicitly
requested it.

- `invalid_argument` / `invalid_sql` / `unsupported_sql`: correct the command or SQL.
- `profile_not_found`: select an existing profile or bind one.
- `authentication_failed` / `connection_failed`: fix credentials or target.
- `database_not_found`: verify the selected database without switching targets.
- `timeout` / `cancelled`: inspect externally visible effects before retrying.
- `comparison_failed`: inspect `error.differences`.
- `execution_failed`: diagnose the MySQL error without silently changing targets.

Inspect only the rows/schema needed for the task. Do not infer a database from a
failed selection, and do not probe after every successful call. Close sessions;
never repeat a write whose outcome is unknown.

## Additional resources

- [references/connections.md](references/connections.md) - profile fields,
  directory binding, keyring, validation, and live-test configuration.
