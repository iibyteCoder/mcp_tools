# Profile and connection configuration

The profile commands manage saved connection settings. SQL commands execute
against the explicitly selected connection. Keep those responsibilities
separate.

## Profile commands

```powershell
db-mysql --json profile list
db-mysql --json profile show billing-dev
db-mysql --json profile set billing-dev --host db.example --port 3306 --user app --database billing
db-mysql --json profile set billing-dev --no-description
db-mysql --json profile validate billing-dev
db-mysql --json profile bind billing-dev --path 'D:\projects\billing'
db-mysql --json profile unbind --path 'D:\projects\billing'
db-mysql --json profile rename billing-dev billing-staging
db-mysql --json profile remove obsolete-profile
```

`profile list` discovers names, non-secret settings and optional descriptions.
`profile show NAME` returns the same non-secret data with credentials masked.
`profile set NAME` creates or updates a profile; omitted settings and
descriptions remain unchanged. `--no-description` clears a saved description.
Password storage goes through the OS credential manager under keyring service
`db-mysql`; the password is kept out of profile JSON, examples, output, logs,
errors, and reports.

Descriptions are usage notes only; store passwords, tokens, and other connection
secrets in the credential store.

`profile validate NAME` performs an explicit connection validation for that
profile. It does not change the profile or directory bindings. A successful
ordinary operation can establish access for that operation, but it does not
replace an explicit validation when validation is requested.

`profile bind NAME --path PATH` creates or updates the direct binding for the
specified directory. `profile unbind --path PATH` removes only that direct
binding; it does not remove the profile and does not alter a parent directory
binding. A path must be explicit when the target directory is not the current
directory.

`profile rename OLD NEW` preserves the profile settings and bindings under the
new name, and must reject an existing destination. `profile remove NAME` removes
the profile and its associated bindings only after the requested removal is
accepted by the CLI.

Root `--profile NAME` selects the connection for the current invocation. It
never creates, removes, or changes a directory binding. Directory binding is
changed only by `profile bind` or `profile unbind`.

## Connection settings and safety

Profiles may contain a host, port, user, default database, character set,
connect timeout, and read timeout. Passwords belong only in the operating-system
credential store; keep them out of `profile show`, JSON output, logs, errors, and
reports.

Use the selected profile, database, and server; report a missing, invalid, or
unavailable selection and keep the requested target unchanged.

- Authentication failures: verify the selected profile's credentials and
  permissions, then explicitly validate it.
- Connection failures: verify the selected host, port, network reachability, and
  service state.
- Timeouts: inspect whether the operation produced an external effect before
  repeating it; repeat only after the outcome is known.
- Cancellation: inspect the visible effect before repeating any mutating
  operation.
