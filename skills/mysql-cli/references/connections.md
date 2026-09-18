# Profile and connection configuration

The profile commands manage saved connection settings. SQL commands execute against the explicitly selected connection. Keep those responsibilities separate.

## Profile commands

```powershell
db-mysql --json profile list
db-mysql --json profile show billing-dev
db-mysql --json profile set billing-dev --host db.example --port 3306 --user app --database billing
db-mysql --json profile validate billing-dev
db-mysql --json profile bind billing-dev --path 'D:\projects\billing'
db-mysql --json profile unbind --path 'D:\projects\billing'
db-mysql --json profile rename billing-dev billing-staging
db-mysql --json profile remove obsolete-profile
```

`profile list` discovers names and binding metadata. `profile show NAME` returns nonsecret saved settings with credentials masked. `profile set NAME` creates or updates a profile; omitted settings remain unchanged. Password entry and storage must go through the CLI's secure configuration or credential store. Never put a password in a command example, output, log, error, or report.

`profile validate NAME` performs an explicit connection validation for that profile. It does not change the profile or directory bindings. A successful ordinary operation can establish access for that operation, but it does not replace an explicit validation when validation is requested.

`profile bind NAME --path PATH` creates or updates the direct binding for the specified directory. `profile unbind --path PATH` removes only that direct binding; it does not remove the profile and does not alter a parent directory binding. A path must be explicit when the target directory is not the current directory.

`profile rename OLD NEW` preserves the profile settings and bindings under the new name, and must reject an existing destination. `profile remove NAME` removes the profile and its associated bindings only after the requested removal is accepted by the CLI.

Root `--profile NAME` selects the connection for the current invocation. It never creates, removes, or changes a directory binding. Directory binding is changed only by `profile bind` or `profile unbind`.

## Connection settings and safety

Profiles may contain a host, port, user, default database, character set, and connection timeout. Passwords belong only in secure configuration or the operating-system credential store. Do not expose them through `profile show`, JSON output, logs, errors, or reports.

There is no silent fallback to localhost, another profile, or another database. If the selected profile is missing, invalid, or unavailable, return the appropriate error and keep the requested target unchanged. Do not switch connections to recover from failure.

- Authentication failures: verify the selected profile's credentials and permissions, then explicitly validate it.
- Connection failures: verify the selected host, port, network reachability, and service state.
- Timeouts: inspect whether the operation produced an external effect before repeating it; never automatically retry a write whose final state is unknown.
- Cancellation: treat the outcome as requiring inspection before repeating any mutating operation.

## Execution boundary

Profile operations manage local connection metadata and explicit validation. SQL operations consume a selected profile and perform server inspection, schema inspection, reads, writes, explanations, benchmarks, or comparisons. Profile commands do not execute application SQL, and SQL commands do not silently edit profiles or directory bindings.

All successful JSON calls return one structured document. A nonzero exit status or `status: "error"` is a failure. Keep stdout free of logs. Stable error codes include `INVALID_ARGUMENT`, `PROFILE_NOT_FOUND`, `AUTH_FAILED`, `CONNECTION_FAILED`, `TIMEOUT`, `CANCELLED`, `SQL_PARSE_FAILED`, `UNSUPPORTED_SQL`, `EXECUTION_FAILED`, and `COMPARISON_FAILED`.
