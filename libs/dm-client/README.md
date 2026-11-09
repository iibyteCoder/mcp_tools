# DM client

`dm-client` is the typed execution library for Dameng DM8 used by `db-dm`.

- `domain`: configuration, enums, errors, requests, results and typed values;
- `ports`: the driver and session protocols;
- `adapters/dmpython`: the only place that imports the official `dmPython`
  driver;
- `execution`: read, write, explain, benchmark, compare, inspection, catalog
  and statistics operations;
- `sql`: the local parser, execution policy and SQL templates.

The package never imports Click, keyring or `dm-cli`. `dmPython` is a runtime
dependency and is isolated at the adapter boundary.
