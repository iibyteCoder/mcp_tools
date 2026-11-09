# `db-dm` Contract

Status: Implemented v1 — batches 0–7 are complete; batch 8 is the final documentation and verification pass; batch 9 adds opt-in `sql explain --actual` through disql autotrace. This file is the authoritative internal contract for the implemented system.

Owner: coordinator (this file), implementation subagents (one batch at a time).

## 1. Scope

`db-dm` is a JSON-only command line tool for Dameng DM8. It mirrors the command
tree and JSON-envelope conventions of `db-mysql`, and adds DM-native catalog and
execution-plan capabilities. All database access goes through `libs/dm-client`.

Non-goals:

- no DM7 support promise;
- no MySQL/Redis changes in this phase;
- no new Docker image or container;
- no UI, daemon, or long-running server;
- no automatic `EXPLAIN` injection into normal reads.

## 2. Command tree

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

Options and semantics:

- `--json` is accepted for compatibility; command output is always one JSON
  document. `help`, `--help` and `--version` are human-readable exceptions.
- `--profile` selects the profile for this invocation. Without it, directory
  binding is used. Without either, `profile` commands still run; `sql` commands
  return local parse diagnostics; `server` and `schema` commands fail with
  `profile_not_found`.
- `--schema` and `--database` are aliases; DM has schemas, not MySQL databases.
- `schema ddl` uses a generic `--type/--name` pair so the same command works for
  tables, views and indexes; `--type` defaults to `table`. `TYPE` is
  `table|view|index|sequence|synonym|procedure|function|package|trigger`.
- `schema analyze` is table-level only in this phase. No `--all`.
- `sql explain` accepts raw SQL (a leading `EXPLAIN` token is stripped) and does
  not accept `--params-file`. Without `--actual` it never executes the SQL.
  `--actual` is opt-in: it executes read-only SQL through the `disql`
  `SET AUTOTRACE TRACEONLY` path, which requires a `disql` executable
  (`DB_DM_DISQL_PATH` names it).

## 3. JSON envelope

Success:

```json
{
  "ok": true,
  "data": {
    "status": "completed",
    "command_group": "sql",
    "action": "explain",
    "profile": "lot-01",
    "result": {}
  },
  "meta": {
    "command_group": "sql",
    "action": "explain",
    "input_source": "inline",
    "output_mode": "json"
  }
}
```

Failure:

```json
{
  "ok": false,
  "error": {
    "code": "execution_failed",
    "message": "……",
    "retryable": false,
    "details": [
      {"error_type": "execution", "argument": null, "source": null, "path": null}
    ],
    "write_outcome": null,
    "differences": []
  },
  "meta": {
    "command_group": "sql",
    "action": "write",
    "input_source": "inline",
    "output_mode": "json"
  }
}
```

Rules:

- stdout contains exactly one JSON document plus one trailing newline; stderr is empty.
- Exit status matches `ExitCode`; `ok:false` and non-zero are both failure signals.
- Passwords, secret values, and sensitive parameter values never appear.
- SQL text is not echoed in results or diagnostics.
- `error.message` is safe to show; `details` carries stable machine-readable context.

## 4. Result contracts

All `metadata` objects contain:

```json
{
  "statement_type": "select",
  "duration_ms": 1.23,
  "row_count": 1,
  "affected_rows": 0,
  "target": {
    "label": "lot-01",
    "host": "127.0.0.1",
    "port": 15237,
    "schema": "TCA_REMIGRATION_20261026",
    "server_version": "8.1.4.80"
  },
  "started_at": "2026-11-08T18:40:00+08:00"
}
```

### 4.1 `sql read`

```json
{
  "columns": [
    {"name": "ID", "type_name": "VARCHAR", "nullable": false, "ordinal": 0}
  ],
  "rows": [{"values": ["A-1"]}],
  "truncated": false,
  "metadata": {}
}
```

`rows` are positional arrays in `columns` order; this preserves duplicate column
names. Values are JSON scalars, arrays or objects. Binary values are Base64;
`Decimal` is a string; date/time values are ISO-8601.

When `--max-rows`/`--max-bytes` are omitted, the client uses 10,000 rows and
1,048,576 bytes, matching `db-mysql`. `truncated` is true when either bound was
hit before the result set was exhausted.

### 4.2 `sql write`

```json
{
  "affected_rows": 1,
  "outcome": "committed",
  "ddl_auto_commit": false,
  "generated_values": [],
  "metadata": {}
}
```

`outcome` is `committed|rolled_back|determined_failure|unknown`.
`ddl_auto_commit` is true when DM auto-committed DDL regardless of requested
transaction mode. `generated_values` stays empty in this phase.

### 4.3 `sql explain`

```json
{
  "format": "text",
  "plan_text": "1   #NSET2: [8, 1, 48]\n2     #PRJT2: ...",
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

- `plan_text` is the verbatim plan returned by `Connection.explain`, minus
  surrounding blank lines.
- `nodes` is best-effort; on parse failure `parse_status=failed`, `nodes=[]`,
  `parse_warning` explains the reason, and the command still succeeds.
- The explained SQL is never executed by `db-dm`.

### 4.3.1 `sql explain --actual`

```json
{
  "provider": "disql-autotrace",
  "executed": true,
  "plan_text": "1   #NSET2: [8, 1, 48]\n2     #PRJT2: ...",
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

- `--actual` is opt-in; without it `sql explain` keeps the estimated
  `Connection.explain` behavior above.
- Actual mode executes the SQL through `disql` with
  `SET AUTOTRACE TRACEONLY`; it is not the dmPython `Connection.explain` path.
- Only read-only SELECT/WITH statements are accepted. INSERT/UPDATE/DELETE/
  MERGE/DDL/CALL/SET and locking or session-state statements are rejected with
  `unsupported_sql`; `EXPLAIN ANALYZE` is rejected with `unsupported_sql`.
  A leading `EXPLAIN` token is stripped and never passed to `disql`.
- `--params-file` is not accepted. The timeout is `--timeout` if supplied,
  otherwise a positive profile `query_timeout`, otherwise the runner default
  (60 seconds).
- Without a profile or directory binding the command returns local parse/policy
  diagnostics only; no `disql` process runs.
- `plan_text` is the estimated optimizer plan. `statistics` and
  `statistics_text` are the actual aggregate `Statistics` block; there is no
  per-operator time or loop count. `autotrace_text` is the sanitized raw output.
- A missing or unusable `disql` executable is `configuration_failed`.
  `disql` failures are `execution_failed`; autotrace timeouts are `timeout`.
- `Duration` is wall-clock time for the `disql` process. The password never
  appears in arguments or output; `disql` receives it only on standard input.

### 4.4 `sql benchmark`

```json
{
  "iterations": 5,
  "warmup_iterations": 1,
  "samples_ms": [0.8, 0.7, 0.75, 0.72, 0.71],
  "minimum_ms": 0.7,
  "maximum_ms": 0.8,
  "average_ms": 0.736,
  "median_ms": 0.72,
  "metadata": {}
}
```

- Read-only only: the policy rejects non-read statements before the first
  iteration. Each timed iteration uses the ordinary read path with
  `max_rows=1`; benchmark never rewrites the SQL, issues only reads, and never
  commits.
- Defaults: `iterations=5` and `warmup_iterations=1`. `--iterations` must be at
  least 1 and at most 100; `--warmup-iterations` must be 0..10. An explicit
  `--warmup-iterations 0` is allowed and produces no warmup runs. Exceeding
  either maximum is `invalid_argument` (exit 2).
- `samples_ms` contains one timing per timed iteration in execution order;
  `minimum_ms`, `maximum_ms`, `average_ms` and `median_ms` are computed from
  those samples. Warmup timings are not included in the samples.
- `--params-file` uses the same positional `?` bindings as `sql read`.

### 4.5 `sql compare`

Both sides are read-only SQL. Each side executes once, in order, and the
results are compared without fetching beyond the ordinary read bounds
(10,000 rows / 1 MiB per side).

`CompareResult`:

```json
{
  "equal": true,
  "left": {
    "columns": [{"name": "ID", "type_name": "INT", "nullable": false, "ordinal": 0}],
    "row_count": 1,
    "truncated": false
  },
  "right": {
    "columns": [{"name": "ID", "type_name": "INT", "nullable": false, "ordinal": 0}],
    "row_count": 1,
    "truncated": false
  },
  "differences": [],
  "metadata": {}
}
```

`CompareSideSummary` fields:

- `columns`: the same `ColumnDefinition` array returned by `sql read`;
- `row_count`: number of materialized rows on that side;
- `truncated`: whether the read bound was hit before the result was exhausted.

`ComparisonDifference` fields:

- `kind`: `column_definition`, `row_count`, `row_value`, `key_column` or
  `duplicate_key`;
- `location`: `columns`, `rows.count`, `row`, `left.missing_key`,
  `right.missing_key`, `left.duplicate_key` or `right.duplicate_key`;
- `key_values`: keyed values as a JSON array, or `null` when the difference is
  not tied to a key tuple;
- `row_index`: zero-based positional row index, or `null` when not positional.

Comparison rules:

- Column names and type names must match exactly and in order; otherwise the
  only reported difference is `column_definition` at `columns`.
- With `--key-column`, key names are case-insensitive. A missing key column is
  `key_column` at `columns`; a duplicate key on a side is `duplicate_key` at
  `left.duplicate_key`/`right.duplicate_key`; a key present on one side only is
  `row_value` at `left.missing_key`/`right.missing_key`; and differing values
  for the same key are `row_value` at `row`.
- Without `--key-column`, row counts are compared first (`row_count` at
  `rows.count`), then rows positionally (`row_value` at `row` with
  `row_index`).
- `--max-diff-samples` defaults to 20 and caps the stored difference samples;
  `0` stores no samples while still reporting `equal=false`. The mismatch
  state itself is not limited by the sample cap.
- No full row payloads are echoed. A truncated side can still compare equal
  within the materialized portion; callers must inspect `left.truncated` and
  `right.truncated`.

An unequal comparison is not a successful `CompareResult`: the CLI emits a
`comparison_failed` error envelope (exit 5) whose `error.differences` contains
the sampled `ComparisonDifference` objects. `equal=true` is the only
successful compare outcome.

### 4.6 `profile` results

Profile view:

```json
{
  "name": "lot-01",
  "description": null,
  "host": "127.0.0.1",
  "port": 15237,
  "user": "TCA_REMIGRATION_20261026",
  "schema": "TCA_REMIGRATION_20261026",
  "connect_timeout": 5.0,
  "query_timeout": 0.0,
  "password_present": true
}
```

- `profile list` → `profiles: [...]`
- `profile show` → `profile: {...}`
- `profile set` → `profile: {...}`
- `profile validate` → `profile`, `validated: true`, `connection_attempted: true`
- `profile bind` → `binding: {path, profile}`
- `profile unbind` → `binding` or null, `unbound`
- `profile rename` → `profile`
- `profile remove` → `removed_bindings`

### 4.7 `server inspect`

```json
{
  "server": {
    "name": "TCA_DM_JSON",
    "instance_name": "TCA_DM_JSON",
    "host_name": "e015478dabaf",
    "version": "DM Database Server x64 V8\n",
    "db_version": "DB Version: 0x7000d",
    "build_version": "03134284368-20250423-270902-20149",
    "build_time": "Apr 23 2025 15:58:16",
    "start_time": "2026-11-02T10:06:02",
    "status": "OPEN",
    "mode": "NORMAL"
  },
  "session": {"user": "TCA_REMIGRATION_20261026", "schema": "TCA_REMIGRATION_20261026"},
  "metadata": {}
}
```

### 4.8 `server capabilities`

```json
{
  "facts": [
    {"name": "compatible_mode", "value": 4, "source": "V$DM_INI"},
    {"name": "case_sensitive", "value": false, "source": "dmPython"},
    {"name": "max_identifier_length", "value": 128, "source": "dmPython"}
  ],
  "metadata": {}
}
```

Values are typed (number/string/boolean/null). `source` names where the value
came from, so a missing fact is not confused with a false value.

### 4.9 `server parameters`

Tabular `columns`/`rows` with:

`PARA_NAME`, `PARA_VALUE`, `SESS_VALUE`, `FILE_VALUE`, `DEFAULT_VALUE`,
`MIN_VALUE`, `MAX_VALUE`, `REDACTED`.

Default returns only `KEY_SERVER_PARAMETERS`; `--all` returns every
`V$DM_INI` row; `--filter` is a case-insensitive substring match against
`PARA_NAME` across all parameters and takes precedence over `--all` and the
default key list. A sensitive name (containing `PWD`, `PASSWORD`, `PASSWD`,
`SECRET`, or `PRIVATE_KEY`) sets all six value columns — `PARA_VALUE`,
`SESS_VALUE`, `FILE_VALUE`, `DEFAULT_VALUE`, `MIN_VALUE`, `MAX_VALUE` — to
`***` and sets `REDACTED=true`; other rows keep their values with
`REDACTED=false`.

### 4.10 `schema databases`

Tabular columns: `SCHEMA_NAME`, `USER_ID`, `IS_SYSTEM`.
Default excludes `SYS`, `SYSDBA`, `SYSAUDITOR`, `SYSSSO`; `--all` includes them.

### 4.11 `schema tables`

Columns: `SCHEMA_NAME`, `TABLE_NAME`, `TEMPORARY`, `PARTITIONED`, `NUM_ROWS`,
`LAST_ANALYZED`.

### 4.12 `schema describe`

Columns: `COLUMN_NAME`, `DATA_TYPE`, `DATA_LENGTH`, `DATA_PRECISION`,
`DATA_SCALE`, `NULLABLE`, `DATA_DEFAULT`, `COLUMN_ID`, `COMMENT`.
Top-level `table_comment` is included.

### 4.13 `schema indexes`

Columns: `INDEX_NAME`, `UNIQUENESS`, `INDEX_TYPE`, `COLUMN_NAME`,
`COLUMN_POSITION`, `DESCEND`, `STATUS`.

### 4.14 `schema stats`

Columns: `TABLE_NAME`, `NUM_ROWS`, `BLOCKS`, `AVG_ROW_LEN`, `SAMPLE_SIZE`,
`LAST_ANALYZED`, `STALE_STATS`.

### 4.15 `schema ddl`

```json
{
  "object_type": "table",
  "schema": "TCA_REMIGRATION_20261026",
  "name": "AICA_FILE_INFO",
  "ddl": "CREATE TABLE ...",
  "metadata": {}
}
```

### 4.16 `schema constraints`

Columns: `CONSTRAINT_NAME`, `CONSTRAINT_TYPE`, `TABLE_NAME`, `COLUMNS`,
`SEARCH_CONDITION`, `REFERENCED_OWNER`, `REFERENCED_TABLE`,
`REFERENCED_COLUMNS`, `DELETE_RULE`, `STATUS`, `VALIDATED`.
`CONSTRAINT_TYPE` is the lowercase `ConstraintType` value
(`primary_key|unique|foreign_key|check|unknown`); DM `P`/`U`/`R`/`C` map to the
first four and any other value maps to `unknown`. `COLUMNS` and
`REFERENCED_COLUMNS` are JSON arrays of column names in constraint position
order; foreign-key referenced columns are resolved from `ALL_CONS_COLUMNS`.

### 4.17 `schema objects`

Columns: `OBJECT_TYPE`, `OBJECT_NAME`, `STATUS`, `CREATED`, `LAST_DDL_TIME`.
`OBJECT_TYPE` is lowercase (`table`, `view`, `index`, ...). Default types:
`table`, `view`, `sequence`, `synonym`, `procedure`, `function`, `package` and
`trigger`; `index` is excluded by default and is returned only with
`--type index`. Package bodies are excluded.

### 4.18 `schema analyze`

```json
{
  "schema": "TCA_REMIGRATION_20261026",
  "table": "AICA_FILE_INFO",
  "partition": null,
  "options": {"estimate_percent": 10.0, "cascade": true, "degree": null},
  "before": {"last_analyzed": null, "num_rows": null},
  "after": {"last_analyzed": "2026-11-08T18:30:00", "num_rows": 77141},
  "outcome": "committed",
  "duration_ms": 123.4,
  "metadata": {}
}
```

No `--transaction`; DBMS_STATS is treated as auto-commit. The success
`outcome` is `committed`; a commit failure is `execution_failed` with
`write_outcome=unknown`. `--cascade` defaults to true; `--estimate-percent`
must be greater than 0 and at most 100, and `--degree` must be at least 1. The
`before`/`after` snapshots report observed statistics rather than assumed
changes.

## 5. Enums and constants

All closed sets are explicit enums in `dm_client.domain.enums` or
`dm_cli.domain.command`; values below are the JSON contract. Do not use raw
literals for these.

| Enum | Values |
| --- | --- |
| `CommandGroup` | `profile`, `server`, `schema`, `sql` |
| `CommandAction` | `list`, `show`, `set`, `validate`, `bind`, `unbind`, `rename`, `remove`, `inspect`, `capabilities`, `parameters`, `databases`, `tables`, `describe`, `indexes`, `stats`, `ddl`, `constraints`, `objects`, `analyze`, `read`, `write`, `explain`, `benchmark`, `compare` |
| `InspectionKind` | `server_inspect`, `server_capabilities`, `server_parameters`, `schema_databases`, `schema_tables`, `schema_describe`, `schema_indexes`, `schema_stats`, `schema_constraints`, `schema_objects`, `schema_ddl` |
| `SqlStatementType` | `select`, `insert`, `update`, `delete`, `merge`, `ddl`, `show`, `describe`, `explain`, `call`, `set`, `other` |
| `ExecutionPolicy` | `read_only`, `write`, `explain`, `analyze` |
| `PolicyViolationReason` | `read_only_requires_read_statement`, `write_requires_write_statement`, `explain_requires_explainable_statement`, `analyze_requires_table`, `read_only_rejects_locking`, `read_only_rejects_session_state` |
| `SqlReadEffect` | `none`, `locking`, `session_state` |
| `TransactionAction` | `commit`, `rollback` |
| `WriteOutcome` | `committed`, `rolled_back`, `determined_failure`, `unknown` |
| `ObjectType` | `table`, `view`, `index`, `sequence`, `synonym`, `procedure`, `function`, `package`, `trigger` |
| `ConstraintType` | `primary_key`, `unique`, `foreign_key`, `check`, `unknown` |
| `ParameterKey` | DB names such as `COMPATIBLE_MODE`, `CASE_SENSITIVE`, `JSON_MODE`, `USE_JSON_DATATYPE`, `BLANK_PAD_MODE`, `LENGTH_IN_CHAR`, `PAGE_SIZE`, `EXTENT_SIZE`, `BUFFER`, `MAX_SESSIONS`, `PORT_NUM`, `INSTANCE_NAME` |
| `SystemSchema` | `SYS`, `SYSDBA`, `SYSAUDITOR`, `SYSSSO` |
| `SensitiveParameterMarker` | `PWD`, `PASSWORD`, `PASSWD`, `SECRET`, `PRIVATE_KEY` |
| `PlanParseStatus` | `parsed`, `partial`, `failed` |
| `SqlParseReason` | `empty`, `multiple_statements`, `unterminated_quote`, `unterminated_comment`, `malformed` |
| `ComparisonDifferenceKind` | `column_definition`, `row_count`, `row_value`, `key_column`, `duplicate_key` |
| `ComparisonLocation` | `columns`, `rows.count`, `row`, `left.missing_key`, `right.missing_key`, `left.duplicate_key`, `right.duplicate_key` |
| `ComparisonSide` | `left`, `right` (internal side label; not emitted) |
| `InputSource` | `inline`, `file`, `stdin`, `params_file` |
| `ParameterKind` | `array` |
| `OutputMode` | `json` |
| `DiagnosticStatus` | `parsed` |
| `CommandStatus` | `completed` |
| `ExitCode` | `0`, `2`, `3`, `4`, `5`, `70` |
| `ErrorCode` | see section 9 |
| `DiagnosticErrorType` | see section 9 |

Rules:

- Enum values are explicit, unique, stable and JSON-serializable. No `auto()`.
- Every enum has a docstring; non-obvious members are commented.
- `ObjectType`, `ConstraintType`, `ParameterKey`, `SystemSchema`,
  `SensitiveParameterMarker`, `SqlParseReason`, `ComparisonDifferenceKind`,
  `ComparisonLocation` and `ComparisonSide` live in `dm-client` domain and are
  reused by the CLI.
- Database-returned data that is not a closed control set (plan operator names,
  type names, free-form status) stays a typed `str`. Do not invent enums for
  unbounded database data.
- Named constants live with their domain: `DEFAULT_DM_PORT = 5236`,
  `DEFAULT_LOGIN_TIMEOUT_SECONDS`, `DEFAULT_QUERY_TIMEOUT_SECONDS`,
  `DEFAULT_FETCH_SIZE`, `DEFAULT_MAX_ROWS = 10_000`,
  `DEFAULT_MAX_BYTES = 1_048_576`, `DEFAULT_BENCHMARK_ITERATIONS = 5`,
  `DEFAULT_BENCHMARK_WARMUP_ITERATIONS = 1`,
  `MAX_BENCHMARK_ITERATIONS = 100`,
  `MAX_BENCHMARK_WARMUP_ITERATIONS = 10`, `DEFAULT_MAX_DIFF_SAMPLES = 20`,
  `REDACTED_VALUE = "***"`, `PLAN_FIRST_LINE_INDENT`, `PROFILE_NAME_PATTERN`,
  `KEY_SERVER_PARAMETERS`, `SYSTEM_SCHEMAS`, `SENSITIVE_PARAMETER_MARKERS`,
  `DISQL_EXECUTABLE_ENV = "DB_DM_DISQL_PATH"`,
  `DEFAULT_DISQL_EXECUTABLE = "disql"`,
  `DEFAULT_ACTUAL_PLAN_TIMEOUT_SECONDS = 60.0`,
  `DISQL_AUTOTRACE_PROVIDER = "disql-autotrace"`.
- `DEFAULT_MAX_ROWS`/`DEFAULT_MAX_BYTES` are the omitted `--max-rows`/
  `--max-bytes` defaults for `sql read` and tabular inspection. `sql compare`
  uses the same default bounds for each side; `sql benchmark` reads one row per
  iteration.
- SQL identifiers/templates live in `dm_client/sql/` modules as named constants
  or builder functions. No SQL strings in application services.

## 6. Module map and dependency rules

### `libs/db-cli-kit`

```text
db_cli_kit/
  __init__.py
  json_codec.py       # JsonValue/JsonObject/encode/parse
  atomic_json.py      # AtomicJsonStore with filelock and atomic replace
  profiles.py         # ProfileName, DirectoryBinding, normalize_directory
  secrets.py          # SecretStore Protocol, KeyringSecretStore(service)
  py.typed
```

Not in the kit: profile settings/registry, command enums, JSON envelopes,
error models, any DB driver, any Click code.

### `libs/dm-client`

```text
dm_client/
  __init__.py
  py.typed
  domain/
    configuration.py
    enums.py
    errors.py
    requests.py
    results.py
    values.py
  ports/
    actual_plan.py
    driver.py
    session.py
  adapters/dmpython/
    connection.py
    cursor.py
    errors.py
    values.py
  adapters/disql/
    __init__.py
    runner.py
  execution/
    executor.py       # dedicated single-thread driver executor
    session.py        # lifecycle/composition only
    read.py
    write.py
    explain.py
    benchmark.py
    compare.py
    inspection.py
    inspection_support.py
    schema_catalog.py
    schema_inspection.py
    schema_maintenance.py
    server_inspection.py
    plan.py
    tabular.py
    target.py
  sql/
    parser.py
    policy.py
    catalog_queries.py
    inspection_queries.py
    analyze_queries.py
```

### `packages/dm-cli`

```text
dm_cli/
  __init__.py
  __main__.py
  composition.py
  domain/
    command.py
    profile.py
  ports/
    profile_store.py
    secret_store.py
  adapters/
    profile_store.py
    secret_store.py
  application/
    actual_plan.py
    errors.py
    input.py
    profile.py
    profile_commands.py
    results.py
    runner.py
    schema_catalog.py
    schema_inspection.py
    schema_maintenance.py
    server_inspection.py
    sql.py
    validation.py
  presentation/click/
    app.py
    failures.py
    rendering.py
    runtime.py
    types.py
    commands/
      profile.py
      schema.py
      server.py
      sql.py
```

Dependency rules:

- `dm-client` never imports `dm-cli`, Click, keyring, platformdirs.
- `dm-client.domain` imports only the standard library.
- `dm-client.ports` imports only `domain`.
- `dm-client.adapters` imports `domain`/`ports`.
- `dm-client.execution` imports `domain`/`ports`/`sql`, never concrete adapters.
- `dmPython` appears only under `dm_client/adapters/dmpython/`.
- `dm-cli.application` imports `domain`/`ports`/`dm_client`, never Click or adapters.
- `dm-cli.presentation` imports `application`/`domain`, never adapters.
- Only `composition.py` constructs adapters.
- `db-cli-kit` imports no DB driver and no Click.
- `tests/test_architecture.py` enforces these edges with AST.

## 7. Shared kit API

```text
AtomicJsonStore(path: Path, lock_timeout: float)
  read() -> JsonObject | None
  write(document: JsonObject) -> None
  update(updater: Callable[[JsonObject | None], JsonObject]) -> JsonObject

KeyringSecretStore(service: str)
  get(name: ProfileName) -> str | None
  set(name: ProfileName, password: str) -> None
  delete(name: ProfileName) -> None

ProfileName(value: str)          # validated; str value
DirectoryBinding(path, profile)  # normalized path
normalize_directory(path) -> Path
```

`AtomicJsonStore` does not validate profile schema or version; each CLI owns
that. `KeyringSecretStore` service names are `db-mysql` and `db-dm`.

## 8. DM-specific semantics

### 8.1 Explain

- `dmPython.Connection.explain(sql) -> str` is the default plan source.
- Pass the raw SQL. Strip one leading `EXPLAIN` token if present.
- Reject `EXPLAIN ANALYZE` with `unsupported_sql`.
- Reject `--params-file` for explain.
- The SQL is never executed by default; no `cursor.execute` in the explain path.
- Plan parsing is best-effort; `plan_text` is authoritative.
- Actual mode (`--actual`) is an explicit opt-in. It starts `disql` with
  `SET AUTOTRACE TRACEONLY`, sends credentials on standard input, and parses the
  output into `ActualPlanResult`. It never opens a dmPython connection.
- Actual mode accepts read-only SELECT/WITH only and rejects everything else
  with `unsupported_sql` before starting `disql`. The `EXPLAIN` prefix is
  stripped and `EXPLAIN ANALYZE` is rejected.
- Actual-mode `plan_text` remains the estimated plan; `statistics` are actual
  aggregate counters. There is no per-operator time or loop count.
- A missing `disql` executable is `configuration_failed`. This path is
  unavailable unless the `disql` executable is installed and configured with
  `DB_DM_DISQL_PATH`.

### 8.2 Parameters

- dmPython uses `qmark` style only: `?` positional parameters.
- `--params-file` accepts a JSON array only. JSON objects are rejected with
  `invalid_params_type` and a message that DM supports positional `?` only.
- No named parameter support is promised.

### 8.3 Connection, schema, timeouts

- `dmPython.connect(schema=...)` sets the default schema. No `SET SCHEMA` in the
  normal path.
- Local verification: an invalid `schema` value is silently ignored by
  `dmPython.connect` (the connection succeeds with the login schema). The client
  reads `conn.current_schema` after connecting and rejects a mismatch instead of
  trusting the connect argument. The mismatch is an intentional typed
  configuration failure, so `profile validate` reports
  `configuration_failed` (exit 5), not `profile_validation_failed`. Typed client
  errors (configuration/connection/authentication) keep their specific codes
  and exit 5; `profile_validation_failed` is reserved for unexpected/non-client
  validator failures.
- `login_timeout` is milliseconds; profile `connect_timeout` is seconds.
- `connection_timeout` is the execution timeout in seconds; profile
  `query_timeout` maps to it; `0` means unlimited. dmPython 2.6.1 accepts only
  whole seconds, so positive fractional values are rounded up. `login_timeout`
  is milliseconds.
- `autoCommit=False` for all sessions. Reads/explain roll back and close.
  Writes commit or roll back per `--transaction`.
- dmPython `threadsafety=1`: all calls for one connection run on a dedicated
  single-thread `ThreadPoolExecutor(max_workers=1)`. Never share a connection
  across threads.

### 8.4 Values and LOB

- Convert `Decimal` to string, date/time to ISO-8601, bytes to Base64.
- Handle `str`, `bytes`, and `dmPython.LOB/BLOB/CLOB` (via `.read()`), closing
  LOB handles after use. Local check returned `str` for CLOB and `bytes` for
  BLOB on a small fixture; both paths must be supported.
- Convert driver tuples/description to `DatabaseRow`/`ColumnDefinition` at the
  adapter boundary; services never see raw DB-API tuples.

### 8.5 Transactions, DDL and statistics

- DDL auto-commits in DM. If `--transaction rollback` is requested for DDL,
  report `outcome=committed` with `ddl_auto_commit=true`; never claim rollback.
- `schema analyze` calls `DBMS_STATS.GATHER_TABLE_STATS`, which persists its
  effect independently of the session transaction. It is treated as
  auto-commit: there is no `--transaction` option, the success outcome is
  `committed`, and a commit failure is `execution_failed` with
  `write_outcome=unknown`.
- `schema analyze` captures `before`/`after` statistics and reports what was
  observed; it does not assume that `NUM_ROWS` or `LAST_ANALYZED` changed.

### 8.6 Redaction and system schemas

- `server parameters` redacts values for names containing the
  `SensitiveParameterMarker` values.
- `schema databases` hides `SystemSchema` members unless `--all`.
- Never log or emit passwords, keyring values, or sensitive parameter values.

## 9. Errors and exit codes

| Code | When | Exit |
| --- | --- | --- |
| `invalid_argument` | bad option/combination | 2 |
| `input_error` | file/JSON/stdin input failure | 3 |
| `unknown_command` | unknown command tree node | 2 |
| `invalid_sql` | empty/multi-statement/unparseable SQL | 2 |
| `unsupported_sql` | policy mismatch, EXPLAIN ANALYZE | 2 |
| `profile_not_found` | unknown profile | 4 |
| `profile_conflict` | duplicate name on rename | 4 |
| `profile_invalid` | invalid settings | 4 |
| `profile_registry_corrupt` | bad registry JSON | 4 |
| `profile_registry_version_unsupported` | unsupported registry version | 4 |
| `profile_registry_locked` | file lock timeout | 4 |
| `secret_store_error` | keyring failure | 4 |
| `profile_validation_failed` | unexpected/non-client validator failure | 4 |
| `configuration_failed` | invalid client configuration | 5 |
| `connection_failed` | TCP/login failure | 5 |
| `authentication_failed` | bad credentials | 5 |
| `permission_denied` | metadata/DBMS_STATS privilege | 5 |
| `object_not_found` | requested table/schema/object absent | 5 |
| `unsupported_object` | GET_DDL does not support the type | 2 |
| `timeout` | execution/login timeout | 5 |
| `cancelled` | user cancellation | 5 |
| `execution_failed` | other database/server failure | 5 |
| `comparison_failed` | two result sets could not be compared | 5 |
| `internal_error` | unexpected bug | 70 |

`DiagnosticErrorType` values mirror the specific error context:
`argument_syntax`, `unknown_command`, `mutually_exclusive_inputs`, `missing_sql`,
`file_not_found`, `file_decode_error`, `file_read_error`, `invalid_params_json`,
`invalid_params_type`, `sql_parse`, `policy_violation`, `profile_not_found`,
`profile_registry_corrupt`, `profile_registry_version_unsupported`,
`profile_registry_locked`, `profile_conflict`, `secret_store_error`,
`profile_validation_failed`, `connection_failed`, `authentication_failed`,
`permission_denied`, `object_not_found`, `unsupported_object`, `timeout`,
`cancelled`, `execution_failed`, `configuration_failed`, `comparison_failed`.

## 10. Test strategy

- Unit tests with fake driver for every client feature.
- Plan parser fixtures for simple, CTE, union and join plans.
- Profile store/keyring tests with temp dirs and fake keyring backend.
- CLI process-level contract tests: one JSON document, exit codes, no stderr,
  no secrets.
- Architecture tests: import edges, no Click/dmPython in wrong layers.
- Live E2E against local DM:
  - connection info: `127.0.0.1:15237`, user/schema
    `TCA_REMIGRATION_20261026` (password only via env `DB_DM_PASSWORD`);
  - local check: the given user does not have `CREATE SCHEMA` privilege
    (`-5512 没有创建模式权限`), so the default is `DB_DM_CLI_TEST_*` tables in
    `TCA_REMIGRATION_20261026`;
  - if a dedicated test schema/user is provided later, make it configurable via
    a named env constant; never assume it exists;
  - all test objects are dropped in `finally`;
  - no new Docker image/container.
- E2E profile: temporary `dm-e2e` profile in an isolated config dir/keyring,
  removed afterward; never persist the supplied password.
- `sql explain` live test asserts plan text/nodes and that a DML explain does not
  change row counts.
- `sql explain --actual` live test requires both `DB_DM_DBA_PASSWORD` and
  `DB_DM_DISQL_PATH`, uses the DBA profile and `disql`, and asserts the estimated
  plan, actual aggregate statistics, and the write/`EXPLAIN ANALYZE` rejections.
  It creates no objects.
- `schema analyze` live test uses a test table with rows, verifies
  `LAST_ANALYZED`/`NUM_ROWS`, then drops the table.

## 11. Batch plan and gates

| Batch | Deliverable | Status | Gates |
| --- | --- | --- | --- |
| 0 | This contract | Complete | Coordinator accepts; no code |
| 1 | `db-cli-kit`, workspace members, dm-client/dm-cli skeletons, profile store/keyring, CLI root/help/version/envelope, `profile` full | Complete | `uv sync`; kit/CLI unit tests; temp profile CRUD; no DB |
| 2a | dm-client core: dmpython adapter, single-thread executor, connection/schema/timeout, parser/policy, read/write, `?` params, LOB/values, errors | Complete | unit tests; live read/write via a small harness; thread affinity review |
| 2b | CLI `sql read/write`, input loading, real `profile validate`, local diagnostics, live E2E | Complete | process tests; live validate/read; test-table write/rollback/cleanup; no secrets |
| 3 | Explain: plan parser, request/result, `execute_explain`, CLI `sql explain` | Complete | plan fixtures; live explain; no execution; prefix stripping; no params |
| 4a | Parity inspection A: `server inspect`, `server capabilities`, `schema databases/tables/describe` | Complete | live commands; comments; system-schema filter; fixed server results |
| 4b | Parity inspection B: `schema indexes`, `schema stats` | Complete | live commands; tabular contracts |
| 5 | DM-native reads: `schema ddl/constraints/objects`, `server parameters` | Complete | live DDL/constraints/objects; fixtures; redaction |
| 6 | `schema analyze` + DDL/statistics commit semantics | Complete | live test table; `LAST_ANALYZED`; permission/outcome |
| 7 | `sql benchmark`, `sql compare`, limits, timeout behavior | Complete | live compare/benchmark; bounds |
| 8 | Full contract tests, live E2E matrix, README/docs, quality gates | Final verification (this batch) | ruff/mypy/pytest/architecture; coordinator reruns |
| 9 (optional) | Migrate `mysql-cli` mechanics to `db-cli-kit` | Optional / deferred | mysql-cli tests unchanged |

Every batch must also pass:

```text
uv sync
uv run ruff check libs/db-cli-kit libs/dm-client packages/dm-cli
uv run python -m mypy libs/db-cli-kit/src libs/dm-client/src packages/dm-cli/src
uv run --project libs/db-cli-kit pytest libs/db-cli-kit/tests
uv run --project libs/dm-client pytest
uv run --project packages/dm-cli pytest
```

## 12. Code standards

- No magic numbers/strings in control flow; enums/named constants only.
- Every enum explicit, documented, unique, JSON-stable.
- Strict models: top-level frozen dataclasses; no `Any` leakage; no anonymous
  business dicts/tuples; no inner classes.
- Single responsibility per module/service; target <= 350 lines per file.
- One-way dependencies; no cycles; no adapter imports from application/presentation.
- One source of truth for JSON values, tabular mapping, target metadata, error
  mapping, SQL templates.
- Reuse Click, filelock, keyring, platformdirs, dmPython, pytest; do not
  reimplement their capabilities.
- Do not over-abstract: concrete services, Protocols only at ports.
- No script/regex bulk source edits. Use targeted `read`/`edit`/`write` and
  review diffs. Regex in product code for parsing/validation is allowed.

## 13. Official documentation and evidence

Verified official docs:

- dmPython interface (includes `Connection.explain`, `connection_timeout`,
  `login_timeout`, `schema`, `paramstyle`, LOB types):
  <https://eco.dameng.com/document/dm/zh-cn/pm/dmpython-interface.html>
- dmPython installation:
  <https://eco.dameng.com/document/dm/zh-cn/pm/dmpython-installation.html>

Empirically verified against local DM 8.1.4.80:

- `conn.explain("SELECT ...")` returns the text plan; `EXPLAIN` prefix is rejected.
- JDBC `EXPLAIN` yields no result set; `EXPLAIN PLAN FOR` is unsupported.
- `V$INSTANCE`, `V$VERSION`, `V$DM_INI`, `V$TABLESPACE` readable.
- `ALL_USERS`, `ALL_TABLES`, `ALL_TAB_COLUMNS`, `ALL_INDEXES`,
  `ALL_IND_COLUMNS`, `ALL_TAB_STATISTICS`, `ALL_CONSTRAINTS`,
  `ALL_CONS_COLUMNS`, `ALL_VIEWS`, `ALL_SEQUENCES`, `ALL_SYNONYMS`,
  `ALL_PROCEDURES`, `ALL_TRIGGERS`, `ALL_DEPENDENCIES` readable.
- `DBMS_STATS.GATHER_TABLE_STATS` accepts `?` bind parameters and persists its
  result even when the session later rolls back. Treat it as auto-commit.
- Local check: `CREATE SYNONYM` is denied for the supplied user (`-5595`), so
  synonym live fixtures are not available; `GET_DDL` for `SYNONYM` remains
  unverified. `TABLE`, `VIEW`, `INDEX` and `SEQUENCE` DDL are verified.
- Local check: `DBMS_STATS` updates `ALL_TAB_STATISTICS.NUM_ROWS` and
  `LAST_ANALYZED`; `schema analyze` can use bind parameters.
- `V$SESSION`, `V$LOCK`, `V$TRX`, `V$CACHEPLN`, `V$PARAMETER`, `V$LICENSE` are
  not usable for the current user; no commands depend on them.

Each batch report must state which official docs were checked and which facts
remain empirical only.

## 14. Verified against local DM

Local server: DM Database Server x64 V8, build `8.1.4.80`. Driver: the official
`dmPython` package, version `2.6.1`.

Live matrix verified during batches 2–7 (batch 8 reruns it when
`DB_DM_PASSWORD` is available):

| Area | Commands / behavior |
| --- | --- |
| Profile | `profile validate` against `127.0.0.1:15237`; requested-schema mismatch detection |
| SQL read/write | positional `?` parameters, DDL auto-commit, write rollback, 10,000-row/1 MiB bounds |
| Explain | text plan and parsed nodes, optional leading `EXPLAIN`, no execution of the explained SQL |
| Server | `server inspect`, `server capabilities`, `server parameters` (default/`--all`/`--filter`, redaction) |
| Schema inspection | `schema databases`, `tables`, `describe`, `indexes`, `stats`, `ddl`, `constraints`, `objects` (default and `--type index`) |
| Schema maintenance | `schema analyze` with DBMS_STATS auto-commit and `before`/`after` statistics |
| Timing/comparison | `sql benchmark`; `sql compare` equal results and the unequal path that raises `comparison_failed` |

The live suite skips unless `DB_DM_PASSWORD` is set. Test tables use the
`DB_DM_CLI_TEST_` prefix, are prefixed per test (`DB_DM_CLI_TEST_CLI_*`,
`DB_DM_CLI_TEST_ANALYZE_*`) and are dropped in `finally`; no Docker image or
additional test schema is required.

## 15. Open decisions

None. All previously open choices are fixed by this contract:

- full MySQL command tree plus DM-native `schema ddl/constraints/objects`,
  `server parameters`, `schema analyze`;
- shared `db-cli-kit` mechanics only (option C);
- explain accepts raw SQL and strips an optional `EXPLAIN`;
- qmark parameters only, JSON array only;
- table-level `schema analyze`;
- system schemas hidden by default;
- no new Docker image; test schema/table creation allowed.
