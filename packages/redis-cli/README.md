# Redis CLI

`db-redis` is a JSON-first Redis command line tool. It keeps named connection
profiles in the user configuration directory and stores passwords in the OS
credential manager.

```powershell
uv run --project packages/redis-cli db-redis --json profile set local `
  --host 127.0.0.1 --port 6379 --no-bind
uv run --project packages/redis-cli db-redis --profile local --json server ping
uv run --project packages/redis-cli db-redis --profile local --json key scan --pattern 'session:*' --limit 20
```

Every successful operation emits `status`, `profile`, and `data`. Failures use
stable error codes and a non-zero exit status.
