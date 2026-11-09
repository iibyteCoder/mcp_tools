# DM CLI connections and profiles

## Profile fields

A DM profile stores only non-secret settings:

| Field | Meaning | Default |
| --- | --- | --- |
| `host` | DM server host | required |
| `port` | DM server port | `5236` |
| `user` | login user | required |
| `schema` | optional default schema; `--no-schema` clears it | login schema |
| `connect_timeout` | login timeout in seconds | `5.0` |
| `query_timeout` | execution timeout in seconds; `0` means unlimited | `0.0` |

`--schema` and `--database` are aliases. `profile show` reports
`password_present` but never the password.

## Create, inspect, validate

```powershell
db-dm --json profile set dm-dev --host 127.0.0.1 --port 5236 `
  --user <user> --schema <schema> --password-stdin

db-dm --json profile list
db-dm --json profile show dm-dev
db-dm --json profile validate dm-dev
```

`--password-stdin` reads the password from standard input. `--password TEXT` is
available for interactive use, but it exposes the value in process arguments;
prefer stdin. `--no-password` clears a stored password.

The profile JSON is written atomically under the platform user config directory
for `db-dm`; passwords are stored separately in the OS credential manager under
keyring service `db-dm`.

## Select a target

- `--profile NAME` selects a profile for one invocation.
- `profile bind NAME [--path PATH]` binds a profile to the current directory or
  an explicit directory; nested directories inherit the nearest binding.
- `profile unbind [--path PATH]` removes the exact binding.
- `profile rename OLD NEW` renames a profile and its bindings.
- `profile remove NAME` removes the profile and all of its bindings.

Without `--profile`, a directory binding is used. If none exists, SQL commands
perform local parse/input diagnostics only; `server` and `schema` commands report
`profile_not_found`. Use only the selected target; report a failed selection.

## Schema validation

`dmPython.connect(schema=...)` may silently keep the login schema when the
requested schema is invalid. `db-dm` reads `current_schema` after connecting and
rejects a mismatch as `configuration_failed` (exit 5). `profile validate` uses
the same path, so an invalid requested schema fails validation rather than
silently using another schema.

## Timeouts

`connect_timeout` is the login timeout in seconds. `query_timeout` maps to the
dmPython execution timeout; `0` means unlimited. dmPython accepts only whole
seconds for the execution timeout, so positive fractions are rounded up.

## Actual plans and `disql`

`sql explain --actual` semantics are documented in `SKILL.md`; this section
covers the client setup.

- Set `DB_DM_DISQL_PATH` to the `disql` executable. If unset, `disql` is looked
  up on `PATH`; a missing executable returns `configuration_failed`.
- Credentials are written to the `disql` process on standard input, never in
  process arguments or output.
- `--timeout` wins over a positive profile `query_timeout`; otherwise the
  `disql` runner default of 60 seconds applies.
- `plan_text` is the estimated plan; `statistics` are actual aggregates. Read
  `SKILL.md` for the `--actual` result shape and read-only rules.

Keep passwords, keyring values, and rendered connection strings out of the
repository, profile JSON, logs, and command output.
