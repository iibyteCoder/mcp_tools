# Connection configuration

## Discover, select and modify

```powershell
db-redis --json profile list
db-redis --json profile current
db-redis --json profile show billing-dev
db-redis --json profile select billing-dev
```

`show NAME` returns saved, password-masked details in `data`. `current` resolves the directory binding. `connection status` exposes current process settings in `data.config` without connecting; pass the same explicit options to inspect an unnamed configuration. In interactive mode it reflects temporary overrides, while `profile current` resolves the directory again.

`profile select NAME` binds the current directory; children inherit the nearest parent binding. Use `--path 'D:\projectsilling'` to bind another directory. Root `--profile NAME` selects a profile without changing directory bindings. Put root options before command groups.

```powershell
# Replace these example values with actual connection details.
db-redis --json profile set billing-dev --host cache.example --port 6379 --password '<password>' --db 2
# Update only supplied fields, preserving other values and existing bindings.
db-redis --json profile set billing-dev --host new-cache.example --port 6380 --no-bind
db-redis --json profile set billing-dev --username app --password '<new-password>' --db 3 --connection-timeout 5 --no-bind
```

`profile set NAME` creates or updates a profile and binds the current directory by default. For updates, omitted fields retain their saved values. `--no-bind` saves without adding/changing a binding. Updating a profile affects every directory using its name.

```powershell
db-redis --json profile rename billing-dev billing-staging
db-redis --json profile clear --path 'D:\projectsilling'
db-redis --json profile remove obsolete-profile
```

`rename OLD NEW` preserves all settings, credentials and directory bindings, and refuses an existing destination. `clear` removes only the direct binding, allowing a parent binding to take effect. `remove` deletes the profile, credential and every binding to it.

All configuration options below can be used with `profile set NAME` for persistence, or at the root for temporary use:

| Option | Meaning |
|---|---|
| `--host`, `--port` | Server and port (1–65535) |
| `--username` | Redis ACL username (empty for no explicit username) |
| `--password` | Password |
| `--db` | Nonnegative logical database number |
| `--connection-timeout` | Positive timeout in seconds |
| `--url` | `redis://[user:password@]host:port/db` |

URL fields replace all URL-supported fields, including omitted fields with URL defaults; individual options override the URL. Use individual options to update only selected fields. Percent-encode reserved characters in URL credentials. To clear credentials, supply empty strings through a shell that preserves empty arguments, or an appropriate passwordless URL.

Precedence: REDIS_* (DB number uses `REDIS_DB`) environment/defaults → nearest directory profile → explicit `--profile` → `--url` → individual options. db-redis does not read MCP's process configuration. Nonsecret settings are at the path returned by `profile list` (Windows: `%APPDATA%\db-cli\connections.json`); passwords are in the OS credential store. Edit through db-redis commands; never print passwords in reports.

## Validate changes

1. `db-redis --json profile show NAME`: check host, port, username and `database` once.
2. `db-redis --profile NAME --json server ping`: require exit 0, `status=success`, expected `profile` and `data.pong=true`. Connection initialization selects the configured DB.
3. Resume work with that profile name. PING does not prove permissions for every Redis command.

Saving or renaming only changes local configuration; it does not verify connectivity. A rename alone preserves validated settings: carry forward the existing validation and check the new name on the next ordinary operation, without another show/probe cycle. After validation, reuse the name without repeated probes. A successful ordinary read can replace a probe if it establishes the necessary access; this does not prove write permissions. On authentication, timeout, missing-credential or database errors, inspect/correct that profile and retry the read-only check. Do not silently fall back to localhost, another user, another profile or another database. Ask only for genuinely missing details.

