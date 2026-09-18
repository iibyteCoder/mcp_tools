---
name: redis-cli
description: Use db-redis to inspect and operate Redis data, and create, modify, rename or validate named connections and directory bindings. Applies to this CLI without requiring MCP or a native database client.
---

# Redis CLI

Use `db-redis --json` for one-shot calls. Ordinary results contain only `profile` as connection metadata. A known, unchanged profile name is enough: do not repeat configuration queries, probes or user confirmations.

## Connections

Use meaningful project/environment names. `--profile NAME` selects a saved connection without changing directory bindings. `profile: null` means no selected profile still matches the active settings; do not assume it refers to an earlier name. An error may report the attempted profile, which does not prove connectivity.

For creation, field changes, renaming, directory binding, password storage or validation, read [references/connections.md](references/connections.md). It documents every configuration option. Inspect `profile show NAME` only when target details are unknown, changed or needed for diagnosis. Pure renames preserve prior validation.

## Results and errors

Read `status`, `profile` and `data`; successful data results omit redundant messages and input echoes. Nonzero exit or `status=error` is a failure. With root `--json`, parameter errors are JSON too; `--help`/`--version` remain plain text. Errors add a stable `code` and optional `hint`:

- `INVALID_ARGUMENT`: correct arguments or input format.
- `PROFILE_NOT_FOUND`: look up `profile list` or configure the intended connection.
- `AUTH_FAILED`: correct credentials/permissions for that profile.
- `CONNECTION_FAILED`: check its address, port and service.
- `TIMEOUT`: a write may already have succeeded; inspect its effect before retrying.
- `EXECUTION_FAILED`: use the message to diagnose; do not blindly retry a write.

Do not silently switch servers, profiles or databases on failure. Ask only for missing information. No extra probe is needed after every successful operation.

## Commands

```powershell
db-redis --profile billing-dev --json key inspect --key session:1 --limit 10 --max-bytes 256
db-redis --profile billing-dev --json key scan --pattern 'session:*' --limit 20
db-redis --profile billing-dev --json server pipeline --commands-file reads.json
```

- `key inspect` returns type, TTL, length and a limited preview for String/Hash/List/Set/Sorted Set. String length is bytes; collection length is items. Preview text is UTF-8 with replacement for cut/invalid bytes. `truncated:true` means more content exists. Hash/set previews are samples; unsupported types return `preview_supported:false`. The byte limit bounds returned preview text; collection members may be downloaded in full before clipping. Multiple reads are not a snapshot.
- `key scan` returns at most `--limit` keys and a short `next_cursor`. Continue with the same connection and pattern using `--cursor TOKEN`; stop only when `next_cursor` is null, even if a page is empty. Tokens keep unreturned keys in a local cache, expire after 24 hours and cannot move to another machine. SCAN can repeat keys and is not a snapshot; deduplicate for complete inventories. Existing `key keys --page N --page-size N` remains available and defaults to a bounded page.
- `server pipeline` accepts nested JSON arrays. Use `--commands-file FILE` (or `-` for stdin) instead of inline `--commands`; they are mutually exclusive. Results are an ordered array with original JSON types and no command echoes. Nonfinite scores use the strings `Infinity`, `-Infinity` or `NaN` because JSON has no such numeric values. Database command errors may follow partial effects; never assume a failed write pipeline rolled back.

Prefer exact keys, narrow patterns, bounded ranges and small batches. Repeat options for simple arrays (`--keys a --keys b`); objects use JSON (`--mapping '{"name":"Ada"}'`). Reads can be combined with mget or a small pipeline. `server flushdb` needs explicit authorization to clear the database and `--confirm`.

Groups: `profile`, `connection`, `key`, `string`, `hash`, `list`, `set`, `zset`, `server`, `skill`, `use`.

Read the specific command's `--help` only for unfamiliar options. `db-redis --json skill path` locates this skill in the installed package. Each shell call connects lazily and closes on exit; a separate `connection connect` cannot persist for later calls. Bare `db-redis` opens interactive mode; `use` only affects that session and may make `profile` null. Prefer named one-shot calls for automation.
