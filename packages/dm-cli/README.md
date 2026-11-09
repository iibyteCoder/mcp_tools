# DM CLI

`db-dm` is a JSON-only command line tool for Dameng DM8. It mirrors the
command tree and JSON envelope conventions of `db-mysql` and keeps all database
access behind `libs/dm-client`.

## Install and run

```bash
# Install the command as a uv tool
uv tool install packages/dm-cli

# Or run it from the workspace without installing
uv run --project packages/dm-cli db-dm --json profile list
```

Create a profile and validate it:

```bash
# --password-stdin reads the password from standard input; --password and
# --no-password are also available.
db-dm --json profile set lot-01 --host 127.0.0.1 --port 5236 \
  --user <user> --schema <schema> --password-stdin

db-dm --json profile validate lot-01
db-dm --json --profile lot-01 sql read --sql "SELECT 1 AS N FROM DUAL"
```

Profiles live in the platform user configuration directory. Passwords are
stored in the OS credential manager under the keyring service `db-dm`, never in
the profile JSON.

## Command tree

```text
db-dm [--json] [--profile NAME] COMMAND

help
--version

profile list
profile show NAME
profile set NAME [--host H] [--port P] [--user U]
                          [--schema S | --database S | --no-schema]
                          [--connect-timeout SEC] [--query-timeout SEC]
                          [--description TEXT | --no-description]
                          [--password TEXT | --password-stdin | --no-password]
profile validate NAME
profile bind NAME [--path PATH]
profile unbind [--path PATH]
profile rename OLD NEW
profile remove NAME

server inspect
server capabilities
server parameters [--filter TEXT] [--all]

schema databases [--all]
schema tables [--schema S | --database S]
schema describe --table T [--schema S | --database S]
schema indexes --table T [--schema S | --database S]
schema stats [--table T] [--schema S | --database S]
schema ddl [--type TYPE] --name NAME [--schema S | --database S]
schema constraints [--table T] [--schema S | --database S]
schema objects [--type TYPE] [--schema S | --database S]
schema analyze --table T [--schema S | --database S]
                          [--partition P] [--estimate-percent N]
                          [--cascade | --no-cascade] [--degree N]

sql read (--sql TEXT | --sql-file PATH | --sql-file -)
         [--params-file PATH] [--max-rows N] [--max-bytes N] [--timeout SEC]
sql write (--sql TEXT | --sql-file PATH | --sql-file -)
          [--params-file PATH] [--transaction commit|rollback] [--timeout SEC]
sql explain (--sql TEXT | --sql-file PATH | --sql-file -)
            [--actual] [--timeout SEC]
sql benchmark (--sql TEXT | --sql-file PATH | --sql-file -)
              [--params-file PATH] [--iterations N]
              [--warmup-iterations N] [--timeout SEC]
sql compare (--left-sql TEXT | --left-sql-file PATH)
            (--right-sql TEXT | --right-sql-file PATH)
            [--left-params-file PATH] [--right-params-file PATH]
            [--key-column NAME ...] [--max-diff-samples N] [--timeout SEC]
```

`--json` is accepted for compatibility; command output is always one JSON
document. `help`, `--help` and `--version` are the human-readable exceptions.
Run `db-dm help` or `db-dm <group> --help` for the Click-generated help text.

## Success envelope

```json
{
  "ok": true,
  "data": {
    "status": "completed",
    "command_group": "sql",
    "action": "read",
    "profile": "lot-01",
    "result": {
      "columns": [{"name": "N", "type_name": "NUMBER", "nullable": true, "ordinal": 0}],
      "rows": [{"values": [1]}],
      "truncated": false,
      "metadata": {}
    }
  },
  "meta": {
    "command_group": "sql",
    "action": "read",
    "input_source": "inline",
    "output_mode": "json"
  }
}
```

`result` varies by action. Tabular reads/inspections contain `columns`, `rows`,
`truncated` and `metadata`; writes contain `affected_rows`, `outcome`,
`ddl_auto_commit`, `generated_values` and `metadata`.

## Error envelope

```json
{
  "ok": false,
  "error": {
    "code": "comparison_failed",
    "message": "comparison results are not equal",
    "retryable": false,
    "details": [
      {"error_type": "comparison_failed", "argument": null, "source": null, "path": null}
    ],
    "write_outcome": null,
    "differences": [
      {"kind": "row_value", "location": "row", "key_values": null, "row_index": 0}
    ]
  },
  "meta": {
    "command_group": "sql",
    "action": "compare",
    "input_source": null,
    "output_mode": "json"
  }
}
```

stdout contains exactly one JSON document plus a trailing newline; stderr is
empty. Exit codes are `0` success, `2` invalid argument/SQL/command, `3` input
error, `4` profile error, `5` execution/comparison error and `70` internal
error. Passwords, keyring values, sensitive parameter values and SQL text are
never echoed.

## `sql explain`

`sql explain` returns the text plan and a best-effort structured parse. It does
not execute the explained SQL and does not accept `--params-file`.

```bash
db-dm --json --profile lot-01 sql explain \
  --sql "SELECT ID, NAME FROM APP.USERS WHERE ID = 1"

# A leading EXPLAIN is optional and is stripped before calling dmPython.
db-dm --json --profile lot-01 sql explain \
  --sql "EXPLAIN SELECT ID, NAME FROM APP.USERS WHERE ID = 1"
```

```json
{
  "format": "text",
  "plan_text": "1   #NSET2: [8, 1, 48]\n2     #PRJT2: [8, 1, 48]",
  "parse_status": "parsed",
  "parse_warning": null,
  "nodes": [
    {
      "line": 1,
      "depth": 0,
      "operation": "NSET2",
      "cost": 8.0,
      "estimated_rows": 1,
      "estimated_bytes": 48,
      "detail": null,
      "text": "#NSET2: [8, 1, 48]"
    }
  ],
  "metadata": {}
}
```

`plan_text` is authoritative. `parse_status` is `parsed`, `partial` or `failed`;
on a partial/failed parse `nodes` may be empty or incomplete and
`parse_warning` explains why, but the command still succeeds.

### `sql explain --actual`

`--actual` is opt-in and executes the read-only SQL instead of only estimating
it. It runs `disql` with `SET AUTOTRACE TRACEONLY`; it does not use the
dmPython `Connection.explain` path. It requires a `disql` executable, named by
`DB_DM_DISQL_PATH` (or `disql` on `PATH`); a missing executable fails with
`configuration_failed`.

```bash
db-dm --json --profile lot-01 sql explain --actual \
  --sql "SELECT ID, NAME FROM APP.USERS WHERE ROWNUM <= 3"
```

```json
{
  "provider": "disql-autotrace",
  "executed": true,
  "plan_text": "1   #NSET2: [8, 1, 48]\n2     #PRJT2: [8, 1, 48]",
  "statistics": [
    {"name": "logical_reads", "value": 12},
    {"name": "exec_time_ms", "value": 3}
  ],
  "statistics_text": "logical reads 12\nexec time(ms) 3",
  "autotrace_text": "1   #NSET2: [8, 1, 48]\n...\nStatistics\nlogical reads 12\nexec time(ms) 3",
  "duration_ms": 456.7,
  "metadata": {}
}
```

- Only SELECT/WITH (read-only) is allowed. INSERT/UPDATE/DELETE/MERGE/DDL/CALL/
  SET, `SELECT ... FOR UPDATE` and `EXPLAIN ANALYZE` are rejected with
  `unsupported_sql` before `disql` runs.
- A leading `EXPLAIN` is stripped; `--params-file` is not accepted.
- `--timeout` wins over a positive profile `query_timeout`; otherwise the
  `disql` runner default of 60 seconds applies.
- Without a profile or directory binding, only local parse/policy diagnostics
  are returned and no `disql` process starts.
- `plan_text` is the estimated optimizer plan. `statistics` and
  `statistics_text` are the actual aggregate `Statistics` block; there is no
  per-operator time or loop count. `autotrace_text` is the raw sanitized output.
- The password is sent to `disql` on standard input and never appears in
  arguments or output.

## `sql read` and `sql write`

DM uses positional `?` parameters only. `--params-file` must contain a JSON
array:

```json
[42]
```

```bash
db-dm --json --profile lot-01 sql read \
  --sql "SELECT ID, NAME FROM APP.USERS WHERE ID = ?" \
  --params-file params.json

db-dm --json --profile lot-01 sql write \
  --sql "INSERT INTO APP.USERS (ID, NAME) VALUES (?, ?)" \
  --params-file params.json
```

`sql read` returns at most 10,000 rows and about 1 MiB per result by default;
use `--max-rows`/`--max-bytes` to change the bounds. `truncated=true` means a
bound was hit before the result was exhausted.

`sql write` commits by default; `--transaction rollback` rolls a DML statement
back. DDL auto-commits in DM, so a DDL result reports `outcome=committed` and
`ddl_auto_commit=true` even when rollback was requested.

`sql benchmark` is read-only and defaults to `--iterations 5` and
`--warmup-iterations 1` (maximum 100 and 10). It returns `samples_ms`,
`minimum_ms`, `maximum_ms`, `average_ms` and `median_ms`.

`sql compare` executes both read-only sides and compares their columns and rows.
Use repeatable `--key-column` for keyed comparison; otherwise rows are compared
positionally. Equal results are a success with `equal=true`; unequal results are
a `comparison_failed` error (exit 5) with samples in `error.differences`.

## Schema and server inspection

```bash
db-dm --json --profile lot-01 server inspect
db-dm --json --profile lot-01 server capabilities
db-dm --json --profile lot-01 server parameters --filter PWD
db-dm --json --profile lot-01 server parameters --all

db-dm --json --profile lot-01 schema databases
db-dm --json --profile lot-01 schema tables --schema APP
db-dm --json --profile lot-01 schema describe --table USERS --schema APP
db-dm --json --profile lot-01 schema indexes --table USERS --schema APP
db-dm --json --profile lot-01 schema stats --schema APP
db-dm --json --profile lot-01 schema ddl --type table --name USERS --schema APP
db-dm --json --profile lot-01 schema constraints --table USERS --schema APP
db-dm --json --profile lot-01 schema objects --schema APP
db-dm --json --profile lot-01 schema objects --type index --schema APP
db-dm --json --profile lot-01 schema analyze --table USERS --schema APP
```

- `server parameters` defaults to the key server parameters; `--all` returns
  every parameter and `--filter` searches all parameter names
  case-insensitively. Sensitive values are reported as `***` with
  `REDACTED=true`.
- `schema constraints` reports lowercase `CONSTRAINT_TYPE` values
  (`primary_key`, `unique`, `foreign_key`, `check`, `unknown`) and array-valued
  `COLUMNS`/`REFERENCED_COLUMNS`.
- `schema objects` excludes indexes by default; request them with
  `--type index`. Object types are lowercase.
- `schema ddl` supports `table|view|index|sequence|synonym|procedure|function|package|trigger`
  and defaults `--type` to `table`.
- `schema databases` hides `SYS`, `SYSDBA`, `SYSAUDITOR` and `SYSSSO` unless
  `--all` is passed.

## `schema analyze` auto-commit

`schema analyze` calls `DBMS_STATS.GATHER_TABLE_STATS` at table level. DM
persists the statistics independently of the session transaction, so the command
has no `--transaction` option and reports `outcome=committed`. It captures
`before` and `after` `last_analyzed`/`num_rows` values and commits explicitly;
a commit failure is reported as `execution_failed` with
`write_outcome=unknown`.

```bash
db-dm --json --profile lot-01 schema analyze --table USERS --schema APP \
  --estimate-percent 10 --cascade
```

`--cascade` defaults to true; use `--no-cascade` to disable it. `--partition`,
`--estimate-percent` (greater than 0 and at most 100) and `--degree` are
optional.

## Profile fields

A profile stores only non-secret settings:

| Field | Meaning |
| --- | --- |
| `host` | DM server host |
| `port` | DM server port; default `5236` |
| `user` | login user |
| `schema` | optional default schema; `--no-schema` clears it |
| `connect_timeout` | login timeout in seconds; default `5.0` |
| `query_timeout` | execution timeout in seconds; `0` means unlimited |

`--schema` and `--database` are aliases. `profile show` reports
`password_present` but never the password. The keyring service name is `db-dm`;
set `DB_DM_CONFIG_DIR` to use an isolated profile directory, which is useful
for tests.

## Tests and live E2E

```bash
uv run --project packages/dm-cli pytest packages/dm-cli/tests -q
```

The live suite is skipped unless `DB_DM_PASSWORD` is set. It uses a temporary
`dm-e2e` profile in an isolated config directory and an in-memory secret store;
the password is never persisted. Test tables are prefixed
`DB_DM_CLI_TEST_` and are dropped in `finally`. No Docker image or additional
test schema is required. The `sql explain --actual` live test skips unless both
`DB_DM_DBA_PASSWORD` and `DB_DM_DISQL_PATH` are also set; it executes a
read-only query through `disql` and creates no objects.

The authoritative internal contract, including error codes and result models,
is [docs/dm-cli-contract.md](../../docs/dm-cli-contract.md).

## Agent skill

The agent-facing skill is
[skills/dm-cli/SKILL.md](../../skills/dm-cli/SKILL.md), with connection details in
[skills/dm-cli/references/connections.md](../../skills/dm-cli/references/connections.md).
