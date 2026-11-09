# Redis profiles and connections

## Profile fields

A Redis profile stores only non-secret settings:

| Field | Meaning | Default |
| --- | --- | --- |
| `host` | Redis host | required |
| `port` | Redis port | `6379` |
| `username` | optional ACL username | empty |
| `database` | logical database | `0` |
| `connection_timeout` | connect/socket timeout in seconds | `5.0` |
| `tls` | use `rediss://` | `false` |

Passwords live only in the OS credential manager under keyring service
`db-redis`. `profile show` reports `password_present` but never the password.

## Create, validate, select

```powershell
db-redis --json profile set local --host 127.0.0.1 --port 6379 --db 0
db-redis --json profile show local
db-redis --json profile validate local
db-redis --json profile select local --path './app'
db-redis --json profile current
db-redis --json use local
db-redis --json profile clear --path './app'
```

`profile set` creates or updates a profile without changing any directory
binding. Bind explicitly with `profile select`, `profile bind`, or `use`.
`profile validate` issues a real PING. `profile clear` removes one binding;
`profile remove` removes the profile, its password, and all bindings.

## Resolution order

Resolve the connection in this order:

1. defaults and supported environment values;
2. the nearest directory binding;
3. `--profile`;
4. `--url`;
5. individual `--host`/`--port`/`--username`/`--password`/`--db` overrides.

Use `connection status` to inspect the resolved non-secret settings without
opening a connection. `connection connect` opens one short-lived connection,
pings, and closes it. Connections do not persist between invocations.

## Skill paths

`db-redis skill path` reports both installed Skill locations:

```json
{"codex":"<home>\\.codex\\skills\\redis-cli\\SKILL.md","dsh":"<home>\\.agents\\skills\\redis-cli\\SKILL.md"}
```

Codex honours `CODEX_HOME`; the DSH path is resolved under the user home.

## Safety

Keep passwords and connection secrets out of profile JSON, logs, errors, and
terminal output. Use the saved credential store or `--password` only when the
environment is trusted. Keep the selected profile, database, and server fixed;
report a failed selection instead of retrying against another target. Repeat a
write only after confirming its outcome.
