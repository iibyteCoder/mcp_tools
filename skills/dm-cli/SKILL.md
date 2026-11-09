---
name: dm-cli
description: This skill should be used when the user asks to inspect or operate a 达梦/Dameng/DM8 database with "db-dm", run or explain DM SQL/执行计划, inspect DM schemas/tables/indexes/constraints/objects, analyze table statistics, benchmark or compare DM queries, or manage DM connection profiles.
---

# DM CLI

`db-dm` is the JSON-only command-line tool for Dameng DM8. Prefer one-shot calls
with `--json`. Every command writes exactly one JSON document to stdout; `help`
and `--version` are intentionally human-readable exceptions. A non-zero exit
status or `ok:false` means failure.

## Command tree

```text
help
--version

profile list|show|set|validate|bind|unbind|rename|remove
server inspect|capabilities|parameters
schema databases|tables|describe|indexes|stats|ddl|constraints|objects|analyze
sql read|write|explain|benchmark|compare
sql explain --actual                  # opt-in disql AUTOTRACE TRACEONLY
```

Examples:

```powershell
db-dm --json profile list
db-dm --json --profile lot-01 server inspect
db-dm --json --profile lot-01 server capabilities
db-dm --json --profile lot-01 server parameters --filter PWD
db-dm --json --profile lot-01 server parameters --all

db-dm --json --profile lot-01 schema databases
db-dm --json --profile lot-01 schema tables --schema APP
db-dm --json --profile lot-01 schema describe --table USERS --schema APP
db-dm --json --profile lot-01 schema indexes --table USERS --schema APP
db-dm --json --profile lot-01 schema stats --table USERS --schema APP
db-dm --json --profile lot-01 schema ddl --type table --name USERS --schema APP
db-dm --json --profile lot-01 schema constraints --table USERS --schema APP
db-dm --json --profile lot-01 schema objects --schema APP
db-dm --json --profile lot-01 schema analyze --table USERS --estimate-percent 10 --cascade
```

- `--schema` and `--database` are aliases; DM calls its namespace a schema.
- Run `db-dm help` for the group list and `db-dm <group> --help` for leaves.
- `--json` is accepted for compatibility; output is always JSON.

## Profiles and connections

Read [references/connections.md](references/connections.md) for profile fields,
directory binding, keyring behavior, and the test configuration override.

A profile stores connection settings; passwords go to the OS credential manager
under keyring service `db-dm` and stay out of profile JSON. Use
`--password-stdin` rather than a password argument.

Select a profile with `--profile`, or bind a profile to the current directory
with `profile bind`. Without `--profile`, a directory binding is used. Keep the
selected target fixed: SQL commands without a target return local parse
diagnostics only, while `server`/`schema` commands report `profile_not_found`.

## SQL input and intent

`sql read`, `sql write`, `sql explain`, and `sql benchmark` accept:

- `--sql TEXT`
- `--sql-file PATH`; `--sql-file -` reads stdin
- `--params-file PATH` (not for `sql explain`)

`--sql` and `--sql-file` are mutually exclusive. SQL files are UTF-8. Each
invocation accepts exactly one statement. The CLI validates and classifies the
statement before execution; it never wraps SQL, adds pagination, or rewrites the
statement.

DM uses positional `?` parameters only. `--params-file` must be a top-level JSON
array of scalars:

```json
[42, "alpha"]
```

An object, scalar, or nested value is rejected with `invalid_params_type`.
The requested command must match the statement classification: `read` for
SELECT/SHOW/DESCRIBE, `write` for INSERT/UPDATE/DELETE/MERGE/DDL/CALL/SET,
`explain` for an explainable query or DML, and `benchmark`/`compare` for reads.

## Explain

`sql explain` returns a text plan and best-effort parsed nodes. By default it
never executes the explained SQL and accepts no `--params-file`.

```powershell
db-dm --json --profile lot-01 sql explain `
  --sql "SELECT * FROM APP.USERS WHERE ID = 1"
```

- A leading `EXPLAIN` is optional and is stripped before calling dmPython.
- `plan_text` is authoritative; `nodes` contains `line`, `depth`, `operation`,
  `cost`, `estimated_rows`, `estimated_bytes`, `detail`, and `text`.
- `parse_status` is `parsed`, `partial`, or `failed`; the command still succeeds
  when parsing is partial, with `parse_warning` explaining why.
- `EXPLAIN ANALYZE` is unsupported and returns `unsupported_sql`.
- The default plan is an estimate.

### Actual plans (`--actual`)

`--actual` executes read-only SQL through `disql` with
`SET AUTOTRACE TRACEONLY`. It requires a `disql` executable named by
`DB_DM_DISQL_PATH`; a missing executable returns `configuration_failed`.
Read [references/connections.md](references/connections.md) for the local
`dm_local` wrapper and profile setup.

```powershell
db-dm --json --profile lot-01-actual sql explain --actual `
  --sql "SELECT * FROM APP.USERS WHERE ROWNUM <= 3"
```

- Allowed only for read-only SELECT/WITH. INSERT/UPDATE/DELETE/MERGE/DDL/CALL/
  SET, `SELECT ... FOR UPDATE` and `EXPLAIN ANALYZE` return `unsupported_sql`
  before `disql` runs.
- A leading `EXPLAIN` is stripped; `--params-file` is not accepted.
- `result` is `ActualPlanResult`: `provider`, `executed`, `plan_text`,
  `statistics`, `statistics_text`, `autotrace_text`, `duration_ms`, `metadata`.
- `plan_text` remains the estimated optimizer plan. `statistics` /
  `statistics_text` are actual aggregate counters; there is no per-operator time
  or loop count.
- Without a profile or directory binding only local diagnostics are returned;
  no `disql` process starts. This mode is opt-in and not the default explain.

## Read, write, benchmark, compare

- `sql read` defaults to at most 10,000 rows / 1 MiB per result. Use
  `--max-rows` / `--max-bytes` to change the bounds; `truncated=true` means a
  bound was hit.
- `sql write` commits by default. `--transaction rollback` rolls back DML. DDL
  auto-commits in DM, so a DDL result reports `outcome=committed` and
  `ddl_auto_commit=true`.
- `sql benchmark` is read-only. It defaults to 5 timed iterations and 1 warmup
  (maximum 100 / 10) and returns `samples_ms`, min/max/average/median.
- `sql compare` executes both sides once and compares columns and rows. Repeat
  `--key-column` for keyed comparison; otherwise rows are compared positionally.
  Key names are case-insensitive. Equal results return `equal=true`; unequal
  results return `comparison_failed` (exit 5) with `error.differences`.

## Server and schema inspection

`server inspect` reports instance/session identity. `server capabilities`
reports typed facts. `server parameters` defaults to key parameters; `--filter`
searches all names case-insensitively and `--all` returns all. Sensitive
parameter values are `***` with `REDACTED=true`.

Tabular inspection results live under `data.result.query` with `columns`, `rows`,
`truncated`, and `metadata`:

- `schema databases` hides `SYS`, `SYSDBA`, `SYSAUDITOR`, `SYSSSO` unless `--all`.
- `schema tables` lists tables; `schema describe` adds table/column comments;
  `schema indexes` and `schema stats` report index columns and statistics.
- `schema ddl --type TYPE --name NAME` returns DM-generated DDL. The `--type`
  choice accepts table/view/index/sequence/synonym/procedure/function/package/
  trigger; DM reports an error when it cannot generate DDL for the object/type.
- `schema constraints` reports lowercase `CONSTRAINT_TYPE` values and array-valued
  `COLUMNS` / `REFERENCED_COLUMNS`.
- `schema objects` excludes indexes by default; use `--type index` to include
  them. Object types are lowercase.
- `schema analyze --table T` calls `DBMS_STATS.GATHER_TABLE_STATS` at table level
  and returns before/after `last_analyzed`/`num_rows`. It has no `--transaction`;
  DBMS_STATS is auto-commit. `--cascade` defaults true; `--partition`,
  `--estimate-percent`, and `--degree` are optional.

## Output and errors

Success envelopes are `ok` + `data` + `meta`; failures are `ok` + `error` +
`meta`. Errors contain a stable `error.code`; keep passwords, keyring values,
sensitive parameter values, and SQL text out of output.

- `invalid_argument` / `invalid_sql` / `unsupported_sql`: correct the command or SQL.
- `profile_not_found`: select an existing profile or bind one.
- `authentication_failed` / `connection_failed`: fix credentials or target.
- `permission_denied`: request the required DM privilege.
- `object_not_found` / `unsupported_object`: verify the catalog object/type.
- `comparison_failed`: inspect `error.differences`.
- `execution_failed`: diagnose the DM error while keeping the selected target.

Inspect only the rows/schema needed for the task. Use the selected database
only; report selection failures. Close sessions after use. Repeat a write only
after confirming its outcome.

## Additional resources

- [references/connections.md](references/connections.md) - profile fields,
  directory binding, keyring, config-dir override, and live-test configuration.
- The workspace contract is `docs/dm-cli-contract.md`; user documentation is
  `packages/dm-cli/README.md`.
