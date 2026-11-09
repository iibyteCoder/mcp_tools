# Redis CLI

`db-redis` is a JSON-first Redis command line tool. It keeps named connection
profiles in the user configuration directory and stores passwords in the OS
credential manager.

```powershell
uv run --project packages/redis-cli db-redis --json profile set local `
  --host 127.0.0.1 --port 6379
uv run --project packages/redis-cli db-redis --json profile select local
uv run --project packages/redis-cli db-redis --json server ping
uv run --project packages/redis-cli db-redis --profile local --json key scan --pattern 'session:*' --limit 20
```

## Output contract

Every invocation emits exactly one compact JSON document followed by one newline.
No logs or human-oriented text are written to stdout.

Successful operations use `ok`, `data`, and `meta`:

```json
{"ok":true,"data":{"pong":true},"meta":{"command_group":"server","action":"ping","profile":"local","output_mode":"json"}}
```

Failures use `ok`, `error`, and `meta`:

```json
{"ok":false,"error":{"code":"profile_not_found","message":"profile not found","retryable":false,"hint":null},"meta":{"command_group":"profile","action":"show","profile":"missing","output_mode":"json"}}
```

`meta.command_group`, `meta.action`, and `meta.profile` are `null` when no
command or profile has been established. `meta.output_mode` is always `"json"`.
Typed Redis data commands report the lowercase Redis command name as the action:
`string get` reports `get`, `key delete` reports `del`.

Error codes are lowercase, and the process exit code depends on the category:

| Error code                                                                    | Exit |
| ----------------------------------------------------------------------------- | ---- |
| `invalid_argument`                                                            | 2    |
| `profile_not_found`, `profile_conflict`, `profile_registry`, `secret_store`   | 4    |
| `auth_failed`, `connection_failed`, `timeout`, `execution_failed`, `cancelled` | 5    |
| `internal_error`                                                              | 70   |

## Profiles and bindings

A profile stores non-secret connection settings and an optional description.
Passwords go to the OS credential manager under the `db-redis` keyring service;
they are never written to profile JSON or command output.

`profile set` never changes directory bindings. Bind explicitly with
`profile select`, `profile bind`, or `use`:

```powershell
db-redis --json profile set local --host 127.0.0.1 --port 6379 --db 0
db-redis --json profile select local --path 'D:\projects\app'
db-redis --json profile current
db-redis --json use local
db-redis --json profile clear --path 'D:\projects\app'
db-redis --json profile validate local
```

Connection resolution order is:

1. defaults and supported environment values;
2. the nearest directory binding;
3. `--profile`;
4. `--url`;
5. individual `--host`/`--port`/`--username`/`--password`/`--db` overrides.

`connection status` reports the resolved non-secret settings without opening a
connection; `connection connect` opens, pings, and closes one session.
Connections do not persist between CLI invocations.

## Skill documents

`db-redis skill path` reports the global Skill document path for both supported
agent runtimes:

```json
{"codex":"C:\\Users\\me\\.codex\\skills\\redis-cli\\SKILL.md","dsh":"C:\\Users\\me\\.agents\\skills\\redis-cli\\SKILL.md"}
```

Codex honours `CODEX_HOME`; the DSH path is resolved under the user home.
