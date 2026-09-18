---
name: mysql-cli
description: Neutral db-mysql command tree for inspecting and operating MySQL data and managing named profiles and directory bindings.
---

# MySQL CLI

The product name is MySQL CLI and the executable is `db-mysql`. Use one-shot calls with `--json`.

## Command tree

```text
help
profile list|show|set|validate|bind|unbind|rename|remove
server inspect|capabilities
schema databases|tables|describe|indexes|stats
sql read|write|explain|benchmark|compare
```

Examples:

```powershell
db-mysql --json profile list
db-mysql --json --profile billing-dev server inspect
db-mysql --json --profile billing-dev server capabilities
db-mysql --json --profile billing-dev schema databases
db-mysql --json --profile billing-dev schema tables --database billing
db-mysql --json --profile billing-dev schema describe --table invoices
db-mysql --json --profile billing-dev schema indexes --table invoices
db-mysql --json --profile billing-dev schema stats --table invoices
db-mysql --json --profile billing-dev sql read --sql "SELECT id, total FROM invoices ORDER BY id"
db-mysql --json --profile billing-dev sql explain --sql "EXPLAIN SELECT id FROM invoices"
db-mysql --json --profile billing-dev sql read --sql-file query.sql
db-mysql --json --profile billing-dev sql write --sql "UPDATE invoices SET total = %s WHERE id = %s" --params-file write.json --transaction commit
db-mysql --json --profile billing-dev sql benchmark --sql "SELECT id FROM invoices" --iterations 10 --warmup-iterations 1
db-mysql --json --profile billing-dev sql compare --left-sql-file old.sql --right-sql-file new.sql --key-column id
```

Read [references/connections.md](references/connections.md) for profile configuration and directory binding.

## Server and schema inspection

The `server` and `schema` commands execute one read-only, parameter-bound inspection against the selected profile. `schema tables`, `schema describe`, `schema indexes`, and `schema stats` accept `--database`; `describe` and `indexes` require `--table`, while `stats` accepts an optional `--table`. When `--database` is omitted, the profile's configured database is used by the metadata query. The command never runs `USE`, changes a profile, or changes the session database.

Inspection results are returned under `data.result` with typed columns, rows, and execution metadata. `server capabilities` reports read-only server capability variables; it does not claim capabilities that were not returned by MySQL.

## SQL input validation

`sql read`, `sql write`, `sql explain`, and `sql benchmark` accept SQL through these inputs:

- `--sql TEXT`
- `--sql-file PATH`; `--sql-file -` reads stdin
- `--params-file PATH`

`--sql` and `--sql-file` are mutually exclusive. SQL files are UTF-8. Passwords are never SQL input and are never accepted inline by this contract.

`sql compare` accepts two explicit inputs: `--left-sql` or `--left-sql-file`, and `--right-sql` or `--right-sql-file`. Its parameter files are `--left-params-file` and `--right-params-file`. Repeat `--key-column` for keyed comparison; `--max-diff-samples` bounds the secret-free difference locations.

Each invocation accepts exactly one SQL statement. The CLI validates and classifies the statement before execution. It does not wrap SQL, add `LIMIT` or `OFFSET`, or paginate results.

The requested intent must match the parser classification: `read` for read statements, `write` for authorized mutations or DDL, and `explain` for an explain statement. `benchmark` and `compare` apply their documented measurement or comparison behavior to the supplied statement while retaining the same input, parsing, and output rules. A mismatch is an error.

`sql write` accepts `--transaction commit|rollback`; a write failure reports whether the request was rolled back, had a determined failure, or reached an unknown state. `sql read` accepts optional client-side `--max-rows` and `--max-bytes` bounds without changing the SQL. `sql benchmark` accepts `--iterations`, `--warmup-iterations`, and `--timeout`; iterations are policy-bounded and never run indefinitely, and only read statements are accepted.

`sql explain` executes the supplied `EXPLAIN` or `EXPLAIN ANALYZE` text exactly as provided. It does not prepend `EXPLAIN`, add a format clause, wrap the query, or probe the target.

With `--json`, stdout contains exactly one `ok`/`data`/`meta` or `ok`/`error`/`meta` document and no logs. A nonzero exit status or `ok: false` means failure. SQL execution requires an explicit `--profile`; without a selected target, the CLI performs local parse/input diagnostics only. Do not silently select another server, profile, or database, and do not run a probe after every successful call.

## Results and errors

Read `data.status`, `data.profile`, and `data.result` from an inspection success document. Errors contain a stable `error.code`; neither errors nor reports contain passwords.

- `invalid_argument`: correct the command, option, or input format.
- `profile_not_found`: inspect `profile list` and select the intended profile.
- `authentication_failed`: correct credentials or permissions for the selected profile.
- `connection_failed`: check the selected server, port, and service.
- `timeout`: determine whether the operation completed before repeating it.
- `cancelled`: inspect any externally visible effect before repeating a mutating operation.
- `database_not_found`: verify the selected database without switching targets.
- `execution_failed`: diagnose the returned database error without silently changing connections.
- `unsupported_sql`: choose a statement supported by the requested SQL command.
- `comparison_failed`: inspect the reported difference locations and correct the comparison inputs.

## Output and execution rules

Keep SQL and passwords out of logs, reports, and output. Inspect only the schema or rows needed for the requested task. Do not infer a database from a failed or missing selection. A known, unchanged profile name is sufficient for subsequent calls; repeated configuration queries and probes are unnecessary. All inspection sessions close their connection, and cancellation or timeout invalidates the affected connection without retrying.
