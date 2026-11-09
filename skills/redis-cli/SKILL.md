---
name: redis-cli
description: Use when the user asks to inspect or operate Redis with "db-redis", manage Redis connection profiles or directory bindings, run typed string/hash/list/set/zset/key operations, scan keys, inspect server information, or execute a bounded Redis pipeline.
---

# Redis CLI

`db-redis` is the JSON-first command-line tool for Redis. It validates command
arguments, manages named connection profiles and directory bindings, and executes
typed Redis operations. Passwords go to the OS credential manager under keyring
service `db-redis`; they are never stored in profile JSON.

## Command tree

```text
help
profile list|current|show|set|select|bind|clear|rename|remove|validate
connection status|connect
server ping|info|dbsize|flushdb|pipeline
key inspect|scan|keys|delete|exists|type|ttl|expire|persist|rename|random
string get|set|mget|mset|incr|append|strlen
hash get|set|getall|delete|exists|keys|values|length
list push|pop|range|length|index|trim
set add|remove|members|card|is-member
zset add|card|range|rank|remove|score
use NAME
skill path
```

Examples:

```powershell
db-redis --json profile list
db-redis --json --profile local server ping
db-redis --json --profile local server info --section memory
db-redis --json --profile local server dbsize
db-redis --json --profile local key scan --pattern "user:*" --limit 20
db-redis --json --profile local key inspect --key user:1 --limit 10
db-redis --json --profile local string set --key greeting --value hello --ex 60
db-redis --json --profile local string get --key greeting
db-redis --json --profile local hash set --key user:1 --mapping '{"name":"Ada","role":"admin"}'
db-redis --json --profile local list push --key queue --value job-1
db-redis --json --profile local zset add --key ranking --mapping '{"ada":10,"bob":7}'
db-redis --json --profile local server pipeline --commands '[["PING"],["DBSIZE"]]'
```

- Run `db-redis <group> --help` for leaf options.
- `--json` is accepted for compatibility; output is JSON.
- `db-redis skill path` prints the global Codex skill path for this tool.

## Profiles and connections

A profile stores non-secret connection settings and an optional description.
Use `profile set` to create/update, `profile show` to inspect without the
password, and `profile validate` to issue a real PING.

```powershell
db-redis --json profile set local --host 127.0.0.1 --port 6379 --db 0
db-redis --json profile validate local
db-redis --json profile select local --path 'D:\projects\app'
db-redis --json profile current
db-redis --json profile clear --path 'D:\projects\app'
db-redis --json use local
```

Connection resolution order is:

1. defaults and supported environment values;
2. the nearest directory binding;
3. `--profile`;
4. `--url`;
5. individual `--host`/`--port`/`--username`/`--password`/`--db` overrides.

Use `connection status` to inspect the resolved non-secret settings without
opening a connection; `connection connect` opens, pings, and closes one session.
Connections do not persist between CLI invocations.

A profile's password is stored in the OS credential manager. Do not put a
password in profile JSON, command output, logs, or reports. `--password` exists
as a temporary override, but prefer the saved credential store.

## Key and data operations

`key scan` returns one bounded SCAN page; use `--cursor` and `--limit` to page.
`key keys` is a bounded compatibility page over SCAN, not an unbounded `KEYS`
replacement. `key inspect` returns type, TTL, length, and a bounded preview;
`--limit` and `--max-bytes` bound the result.

Data commands are typed by family:

- `string`: get/set, mget/mset, incr, append, strlen. `string set` supports
  `--ex`, `--px`, `--nx`, `--xx`.
- `hash`: get/set/getall, field existence, keys/values, length; `--mapping` is a
  JSON object of field/value strings.
- `list`: push/pop, range, length, index, trim; use `--right` for the right end.
- `set`: add/remove/members/card/is-member.
- `zset`: add/card/range/rank/remove/score; `--mapping` is a JSON object of
  member/score pairs.

Destructive operations must be explicit:

```powershell
db-redis --json --profile local key delete --key obsolete
db-redis --json --profile local server flushdb --confirm
```

`server flushdb` clears the selected logical database; it is never implied by a
read command. `server pipeline` executes an ordered JSON array of Redis commands
and supports `--commands-file` (including `-` for stdin).

## Output and errors

Success documents have `status`, `profile`, and `data`. Failures have `status`,
`profile`, and a stable `error.code` / `error.message`. A non-zero exit status or
a non-success status means failure. Do not parse human-oriented text.

Common errors (stable uppercase codes):

- `INVALID_ARGUMENT`: correct the command, option, or mapping JSON.
- `PROFILE_NOT_FOUND`: inspect `profile list` and select the intended profile.
- `PROFILE_CONFLICT`: choose a different profile name or resolve the conflict.
- `PROFILE_REGISTRY_ERROR` / `SECRET_STORE_ERROR`: inspect local profile or
  credential storage; do not bypass the store.
- `AUTH_FAILED` / `CONNECTION_FAILED`: fix credentials or target.
- `TIMEOUT` / `EXECUTION_FAILED`: inspect externally visible effects before
  retrying; diagnose the Redis error without silently changing targets.
- `INTERNAL_ERROR`: report the failure rather than guessing at a recovery.

Keep passwords and connection secrets out of logs, reports, and output. Use
bounded scans and bounded previews; do not issue unbounded key enumerations.
Do not silently switch profiles, databases, or servers.

## Maintenance conventions

- Redis driver APIs enter the application only through
  `redis_cli.client.RedisClient`; third-party return values are converted at the
  boundary.
- New serializable results belong in `json_types.py` as named types.
- Profile metadata is written atomically by `store.py`; secrets are managed only
  by `secrets.py`; command handlers do not access files or keyring directly.
