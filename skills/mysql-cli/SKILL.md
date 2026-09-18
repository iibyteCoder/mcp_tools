---
name: mysql-cli
description: Neutral db-mysql command tree for inspecting and operating MySQL data and managing named profiles and directory bindings.
---

# MySQL CLI

The product name is MySQL CLI and the executable is `db-mysql`. Prefer one-shot calls with `--json`.

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
db-mysql --json --profile billing-dev schema describe --table invoices
db-mysql --json --profile billing-dev sql read --sql "SELECT id, total FROM invoices ORDER BY id"
db-mysql --json --profile billing-dev sql explain --sql "EXPLAIN SELECT id FROM invoices"
db-mysql --json --profile billing-dev sql read --sql-file query.sql
```

Read [references/connections.md](references/connections.md) for profile configuration and directory binding.

## SQL contract

`sql read`, `sql write`, `sql explain`, `sql benchmark`, and `sql compare` accept SQL through these inputs:

- `--sql TEXT`
- `--sql-file PATH`; `--sql-file -` reads stdin
- `--params-file PATH`

`--sql` and `--sql-file` are mutually exclusive. SQL files are UTF-8. Passwords are never SQL input and are never accepted inline by this contract.

Each invocation accepts exactly one SQL statement. A MySQL-dialect parser validates and classifies it before execution. The CLI does not wrap SQL, add `LIMIT` or `OFFSET`, or paginate results. `EXPLAIN` and `EXPLAIN ANALYZE` execute exactly as supplied. Unknown-state writes are never retried automatically.

The requested intent must match the parser classification: `read` for read statements, `write` for authorized mutations or DDL, and `explain` for an explain statement. `benchmark` and `compare` apply their documented measurement or comparison behavior to the supplied statement while retaining the same input, parsing, and output rules. A mismatch is an error.

With `--json`, stdout contains exactly one structured document and no logs. Nonzero exit status or `status: "error"` means failure. Do not silently select another server, profile, or database, and do not run a probe after every successful call.

## Results and errors

Read `status`, `profile`, and `data` from the JSON document. Errors contain a stable `code` and may contain a safe `hint`; neither errors nor reports contain passwords.

- `INVALID_ARGUMENT`: correct the command, option, or input format.
- `PROFILE_NOT_FOUND`: inspect `profile list` and select the intended profile.
- `AUTH_FAILED`: correct credentials or permissions for the selected profile.
- `CONNECTION_FAILED`: check the selected server, port, and service.
- `TIMEOUT`: determine whether the operation completed; never retry a write with unknown state automatically.
- `CANCELLED`: the operation was cancelled; inspect any externally visible effect before repeating it.
- `SQL_PARSE_FAILED`: correct the MySQL syntax or statement input.
- `UNSUPPORTED_SQL`: choose a supported statement or command intent.
- `EXECUTION_FAILED`: diagnose the returned database error without silently changing connections.
- `COMPARISON_FAILED`: correct the comparison inputs or investigate the reported difference.

## Output and execution rules

Keep SQL and passwords out of logs, reports, and output. Inspect only the schema or rows needed for the requested task. Do not infer a database from a failed or missing selection. A known, unchanged profile name is sufficient for subsequent calls; repeated configuration queries and probes are unnecessary.
