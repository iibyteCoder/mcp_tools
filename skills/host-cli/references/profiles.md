# Profile and credential configuration

Profiles hold the connection facts of one host. The password is never among
them: it lives in the operating-system credential store, keyed by profile name.

## Profile commands

The command surface matches the sibling CLIs (`db-mysql`, `db-redis`):

```powershell
host-cli profile list
host-cli profile show web01
host-cli profile set web01 --host 10.0.0.11 --user ops
host-cli profile set web01 --host 10.0.0.11 --user ops --port 2222 --description "app server"
host-cli profile set web01 --port 2222
host-cli profile set web01 --no-description
host-cli profile rename web01 web02
host-cli profile remove web01
host-cli profile validate web01

host-cli profile set-password web01 --password-stdin
host-cli profile clear-password web01
```

`profile set` is an upsert, like its siblings: one command creates and updates,
and omitted fields keep their stored value. The cost is that a misspelled name
silently creates a second profile instead of failing, so `profile list` is the
check after adding a host.

`profile rename` carries the stored password to the new name and refuses a
destination that already exists. It writes the new entry before removing the old
one, so an interruption can leave a duplicate but never a loss.

`profile validate` sends `true` and reports the ordinary run envelope. It proves
reachability, host key and credentials in one round trip without changing
anything.

## What is deliberately absent

`bind` / `unbind` / `select` / `current` do not exist. Siblings offer directory
bindings because picking the wrong database is usually recoverable; picking the
wrong host is not. Every `run` therefore names its profile.

`--password` on the command line does not exist either. A password in arguments
appears in process listings and shell history, so `set-password --password-stdin`
is the only way in.

## Fields

| Field | Required | Default | Meaning |
|---|---|---|---|
| `host` | yes | - | host name or address |
| `user` | yes | - | login account on the host |
| `port` | no | 22 | TCP port |
| `description` | no | none | free-text note; see the caveat below |
| `command_timeout` | no | 60 | default bound in seconds for `run` |
| `read_only` | no | false | refuse anything that is not inspection |
| `max_commands_per_minute` | no | 0 (unlimited) | invocations allowed per sliding minute |
| `requires_approval` | no | false | refuse every run until a token is supplied |

`profile list` reports every field plus `password_present`, which is asked of the
credential store at read time rather than stored. The registry therefore cannot
claim a password the keyring no longer holds.

## The three gates

```powershell
host-cli profile set prod01 --read-only
host-cli profile set prod01 --writable
host-cli profile set prod01 --max-commands-per-minute 10
host-cli profile set prod01 --requires-approval
host-cli profile set prod01 --no-approval
```

`--read-only` and `--writable` are the two directions of one setting, as are
`--requires-approval` and `--no-approval`. Passing neither leaves the stored value
alone, like every other `set` option.

Read-only has no per-call override: `--force` refers to the danger guard and does
not clear it. That is deliberate -- a mode an agent can bypass for one call is not
a guarantee.

A rate ceiling of `0` means unlimited. Refused calls still count against the
window, so retrying after a `rate_limited` failure does not help; wait for the
window to drain.

Gate settings added after a registry already existed are read leniently: a
`profiles.json` written before them loads with all three off, which preserves the
previous behaviour instead of silently making every old profile read-only. Unknown
keys are still an error, so a typo does not pass unnoticed.

## Credentials

The password goes to the OS credential store under service `host-cli`, account
`= profile name`. It is kept out of the profile file, every command line, all
output, the audit log, and error messages.

`--password-stdin` is the only input path, and is required: a password is never
accepted as an argument, because process listings and shell history expose
arguments.

The password is bound to the profile **name**, not to `user@host`. Changing a
host or user keeps the stored password, and `profile set` reports that it is being
reused for the new target.

`profile clear-password` removes the stored password while keeping the profile,
so key-based authentication continues to work.

## Storage locations

All of these follow the platform's per-user directories:

| Content | Location |
|---|---|
| profiles | `%LOCALAPPDATA%\host-cli\host-cli\profiles.json` |
| approvals | `%LOCALAPPDATA%\host-cli\host-cli\approvals.json` |
| rate counter | `%LOCALAPPDATA%\host-cli\host-cli\rate.json` |
| passwords | Windows Credential Manager, service `host-cli` |
| audit log | `%LOCALAPPDATA%\host-cli\host-cli\Logs\audit.jsonl` |

The profile file is replaced atomically under a lock, so a crash mid-write leaves
the previous contents intact. A file that cannot be parsed fails with
`profile_registry_corrupt` rather than being silently reset.

**Deleting `approvals.json` or `rate.json` is safe.** The first loses outstanding
approvals (request one again); the second resets the rate window. Neither is
authoritative -- the audit log is.

`approvals.json` holds only command digests, never commands. `rate.json` holds
only timestamps. Neither can reconstruct what was about to run.

That is also their limit: they prove the tool consulted them, not that a human
approved anything. An approval is a speed bump for accidents, not a defence
against a hostile process running as the same user.

## Read-only profiles refuse tools they do not recognise

The inspection list lives in `host_cli/domain/intent.py`. If a genuinely
read-only tool is refused, the options are:

1. mark the profile writable (if the machine may be changed), or
2. add the tool to `INSPECTION_COMMANDS`, or
3. add the subcommand to `INSPECTION_SUBCOMMANDS` if it is a subcommand of a
   recognised command (`systemctl status` is listed; `systemctl restart` is not).

Adding a tool is a deliberate act with a review: the default is refusal precisely
so that an unknown tool cannot be waved through.

## Descriptions are hints, not facts

A description may say "runs nginx, A team owns it, do not touch /data". The tool
never reads it to make a decision, never parses it, and never treats it as
current. It is written by a person at some past moment and rots accordingly.

To learn what a host is actually running, ask the host:

```powershell
host-cli run 'ps aux --sort=-%mem | head' --profile web01
```
