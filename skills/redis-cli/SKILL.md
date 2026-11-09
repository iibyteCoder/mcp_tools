---
name: redis-cli
description: This skill should be used when the user asks to inspect or operate Redis with "db-redis", manage Redis connection profiles or directory bindings, run typed string/hash/list/set/zset/key operations, scan keys, inspect server information, or execute a bounded Redis pipeline.
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
- `db-redis skill path` reports both the Codex and DSH global Skill document
  paths.

## Profiles and connections

Read [references/connections.md](references/connections.md) for profile fields,
directory binding, URL precedence, keyring behavior, and Skill paths.

Passwords go to the OS credential manager under keyring service `db-redis` and
stay out of profile JSON. `profile set` saves settings without binding; bind
explicitly with `profile select`, `profile bind`, or `use`. Select a profile with
`--profile`, or let the nearest directory binding choose one. Keep the selected
profile, database, and server fixed; report a failed selection.

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

Every invocation emits exactly one compact JSON document followed by one
newline. Successful operations use `ok`, `data`, and `meta`:

```json
{"ok":true,"data":{"pong":true},"meta":{"command_group":"server","action":"ping","profile":"local","output_mode":"json"}}
```

Failures use `ok`, `error`, and `meta`:

```json
{"ok":false,"error":{"code":"profile_not_found","message":"profile not found","retryable":false,"hint":null},"meta":{"command_group":"profile","action":"show","profile":"missing","output_mode":"json"}}
```

`meta.command_group`, `meta.action`, and `meta.profile` are `null` when no
command or profile has been established; `meta.output_mode` is always `"json"`.
Typed data commands report the lowercase Redis command name as the action
(`string get` reports `get`, `key delete` reports `del`). A non-zero exit status
or `ok: false` means failure. Parse only JSON.

Error codes are lowercase, and the process exit code depends on the category:

- `invalid_argument`: correct the command, option, or mapping JSON (exit 2).
- `profile_not_found`: inspect `profile list` and select or bind the intended
  profile (exit 4).
- `profile_conflict`: choose a different profile name or resolve the conflict
  (exit 4).
- `profile_registry` / `secret_store`: use the profile and credential store;
  inspect local storage when it fails (exit 4).
- `auth_failed` / `connection_failed`: fix credentials or target (exit 5).
- `timeout` / `execution_failed` / `cancelled`: inspect externally visible
  effects before retrying; diagnose the Redis error without silently changing
  targets (exit 5).
- `internal_error`: report the failure rather than guessing at a recovery
  (exit 70).

Keep passwords and connection secrets out of logs, reports, and output. Use
bounded scans and bounded previews. Keep the selected profile, database, and
server fixed; report a failed selection instead of retrying against another
target.

## Additional resources

- [references/connections.md](references/connections.md) - profile fields,
  directory binding, URL precedence, keyring, Skill paths, and connection safety.
