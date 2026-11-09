# Shared CLI kit

`db-cli-kit` contains database-neutral mechanics shared by the `db-*` command
line tools:

- `json_codec`: explicit `JsonValue`/`JsonObject` encoding and parsing;
- `AtomicJsonStore`: file-locked, atomic JSON persistence;
- `profiles`: validated profile names, directory bindings and path
  normalization;
- `secrets`: the `SecretStore` protocol and a keyring-backed implementation.

The kit deliberately contains no database drivers, no Click code, no CLI
envelopes and no database-specific profile schema.
