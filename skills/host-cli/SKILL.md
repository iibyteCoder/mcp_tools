---
name: host-cli
description: This skill should be used when the user asks to run a command on a remote host, inspect a remote machine's processes, logs, disk, or services, manage saved SSH host profiles or their stored passwords, preview whether a command would be refused by any of the four safety gates, or read back the local audit trail of what was executed with "host-cli".
---

# Host CLI

`host-cli` sends one command to a configured host and reports exactly what came
back. It does not wrap, interpret or judge the command itself: whatever is sent
runs on the remote shell as written.

Passwords live in the operating-system credential store (keyring service
`host-cli`, account = profile name) and never in the profile file, never in an
argument, never in any output.

## Command tree

```text
profile list
        show NAME
        set NAME [--host --user --port --description/--no-description
                  --command-timeout --read-only/--writable
                  --max-commands-per-minute --requires-approval/--no-approval]
        rename OLD NEW
        remove NAME
        set-password NAME --password-stdin
        clear-password NAME
        validate NAME [--timeout SECONDS]

run <COMMAND> --profile NAME [--timeout SECONDS] [--force] [--dry-run]
                            [--request-approval | --approve TOKEN]

audit summary
      show [--limit N] [--status executed|blocked|dry_run]

skill
--version
```

There is **no `help` subcommand** -- use `--help` on any level.

## Quick start

```powershell
host-cli profile set web01 --host 10.0.0.11 --user ops --description "app server, A team owns it"
host-cli profile set-password web01 --password-stdin
host-cli profile validate web01
host-cli run 'ps aux | head' --profile web01
```

## Profile management

`profile` matches the sibling CLIs (`db-mysql`, `db-redis`) command for command:
`list`/`show`/`set`/`rename`/`remove`/`validate` behave the same way, with `set`
acting as an upsert and omitted fields keeping their stored value.

**The upsert has a cost worth knowing**: a misspelled profile name silently
creates a second profile rather than failing. Run `profile list` after adding a
host.

```powershell
host-cli profile set web01 --port 2222      # only the port changes; host/user kept
host-cli profile set web01 --no-description # remove the note
host-cli profile rename web01 web02         # carries the stored password across
host-cli profile remove web01               # deletes the profile and its password
```

`rename` writes the new entry before removing the old, so an interruption can
duplicate but never lose the password. It refuses a destination that exists.

`validate` sends `true`: the smallest command that proves reachability, host key
and credentials while changing nothing. It is the only command this tool picks on
the caller's behalf.

Where this tool deliberately differs from its siblings:

- **no `bind`/`unbind`/`select`/`current`** -- there is no directory binding, so
  every `run` names its profile explicitly. A wrong host is not recoverable the
  way a wrong database is.
- **`set-password`/`clear-password` instead of `--password`** -- a password on a
  command line is visible in process listings and shell history.

## The four gates

Every `run` passes four gates in this order. A command refused by an earlier gate
never consumes a rate slot.

| gate | configured by | refuses | escape |
|---|---|---|---|
| danger | built in, 10 categories | irreversible operations | `--force` |
| read-only | `profile set NAME --read-only` | anything not inspection | **none** |
| approval | `profile set NAME --requires-approval` | runs with no token | `--approve TOKEN` |
| rate | `profile set NAME --max-commands-per-minute N` | over the per-minute ceiling | wait for the window |

### Gate 1: danger detection

Matching is structural, not textual: `/bin/rm -rf /`, `busybox rm -rf /`,
`sudo -u root /usr/bin/rm -rf /etc` and `sh -c 'rm -rf /'` are one act written
four ways and are treated identically.

| category | example |
|---|---|
| `recursive_delete` | `rm -rf /`, `find / -delete`, `truncate -s0 /etc/passwd`, `mv /etc /etc.bak`, `docker system prune -a --volumes`, `rsync --delete`, `tar -C /` |
| `access_lockout` | `systemctl stop sshd`, `systemctl disable firewalld`, `ip link set eth0 down`, `iptables -P INPUT DROP`, `crontab -r`, `userdel -r`, `kill -9 1` |
| `redirect_truncate` | `echo x > /etc/passwd`, `cat /dev/null > /etc/shadow`, `> /etc/fstab` |
| `permission_open` | `chmod -R 777 /var`, `chown -R nobody /` |
| `disk_write` | `dd of=/dev/sda`, `mkfs.ext4 /dev/sdb1` |
| `power_state` | `shutdown`, `reboot`, `halt` |
| `firewall_flush` | `iptables -F` |
| `audit_tamper` | `systemctl stop auditd`, `history -c`, `rm -rf /var/log` |
| `fork_bomb` | `:(){ :|:& };:` |
| `unresolved` | `rm -rf $TARGET`, `rm -rf $(cat path)` |

Refused with `dangerous_command` unless `--force` is passed.

**`access_lockout` is about reachability, not data.** A host that lost `/etc` can
still be logged into; a host whose sshd was masked cannot, which turns a
recoverable mistake into a console trip. `systemctl restart` is deliberately *not*
flagged -- restarting a service is ordinary work, and flagging it would teach the
operator to pass `--force` by reflex.

**`redirect_truncate` is about the shell, not the command.** `echo x > /etc/passwd`
empties the file while the command name stays innocent. `>>` never truncates and
is left alone; `/dev/null`-class devices are exempt.

**`unresolved` is not a clean result.** It means the guard could not determine
what the command would touch. Treat it as "unknown", never as "safe".
`rm -rf $BUILD_DIR` legitimately trips it; pass `--force` when the value is known
and harmless.

**This gate is a seatbelt, not a brake.** It cannot stop `eval`, `base64 | sh`,
`python -c '...'` or any other re-spelling through a different interpreter.
Prevention belongs to host permissions; this gate reduces accidents and leaves
evidence.

### Gate 2: read-only profiles

Inverts the question: not "is this irreversible" but "could this change
anything". Anything not recognised as inspection is refused.

```text
ALLOWED   ps, df, tail, grep, journalctl, systemctl status, docker ps, ip addr, ls, cat, find (without -delete/-exec)
REFUSED   systemctl restart, rm, mkdir, sed -i, echo x > /tmp/out, unknown tools
```

Marking and unmarking:

```powershell
host-cli profile set prod01 --read-only
host-cli profile set prod01 --writable
```

There is **no per-call override** -- `--force` does not clear it, because a mode
that can be waved through for one call is advisory rather than a guarantee.

The trade is explicit: a genuinely read-only tool the list has never heard of is
refused too. If that happens, either mark the profile writable or add the tool to
`host_cli/domain/intent.py`.

### Gate 3: approval

```powershell
host-cli run 'systemctl restart nginx' --profile prod01 --request-approval
# -> {"token":"3f9a2c1d", "expires_at":"..."}    nothing was executed

host-cli run 'systemctl restart nginx' --profile prod01 --approve 3f9a2c1d
```

The token is bound to the exact command, the exact profile, and a ten-minute
expiry. It cannot be reused for another command (`approval_required` with "issued
for a different command"), transplanted to another profile, or kept indefinitely.
Only a SHA-256 digest of the command is stored, never the command itself.

`--request-approval` and `--dry-run` cannot be combined: one is asking for
permission and the other is asking what would happen.

### Gate 4: rate ceiling

```powershell
host-cli profile set prod01 --max-commands-per-minute 10   # 0 = unlimited, the default
```

Caps invocations per sliding minute. This guards the failure none of the others
can see: not a wrong command but a caller that will not stop. An agent in a retry
loop can send hundreds of harmless commands.

A refused call still counts, so retrying does not help -- wait for the window to
drain. The counter is shared per profile across the machine, not per process.

## The dry run

```powershell
host-cli run 'rm -rf /var/tmp/build' --profile web01 --dry-run
```

Sends nothing and reports what **all four** gates would decide:

```json
{"dry_run": true, "verdict": "clear", "would_block": true, "refused_by": "read_only_violation"}
```

`refused_by` names the gate, so a green `would_block` is not mistaken for "the
danger guard is fine with it". Use it before any command you are unsure about.

## Output contract

One compact JSON document per invocation, always:

```json
{"ok":true,"data":{"...":1},"error":null}
{"ok":false,"data":null,"error":{"code":"dangerous_command","message":"..."}}
```

`data` survives failure on purpose: when a remote command exits non-zero or times
out, its output is what the operator needs. Branch on `error.code`; never parse
`message`.

`error` carries three optional evidence fields: `host_key_problem`, `fingerprint`
and `danger_excerpts`.

## Outcomes

Exactly one `outcome` describes every invocation:

| `outcome` | Meaning |
|---|---|
| `success` | remote command exited 0 |
| `remote_nonzero_exit` | remote command exited non-zero; `data.remote_exit_code` is the real status |
| `remote_killed_by_signal` | remote process was killed by a signal |
| `timeout` | local bound expired; `data.remote_state` is `unknown` |
| `authentication_failed` | credentials rejected, or none stored |
| `host_key_untrusted` | host key unknown or changed; `error.host_key_problem` says which |
| `connection_failed` | DNS, refused, reset, banner failure |
| `credential_store_unavailable` | the OS credential store could not be read or written |
| `ssh_client_unavailable` | no ssh client on `PATH` |

## Non-interactive by design

- No pty is allocated, so `vim`, `top`, `less` and `sudo` requiring a terminal do
  not work. Use `sudo -n` (non-interactive) when a command needs elevation.
- stdin is closed at the far end: a command reading stdin sees EOF immediately
  rather than hanging.
- The command runs in the login shell, starting in the home directory, with the
  remote environment inherited and nothing injected. To check what that
  environment actually is, run `echo $PATH`.
- A background process that keeps stdout open holds the session until the
  timeout. Redirect its output to return immediately:
  `nohup cmd >/dev/null 2>&1 &`.
- Output is capped at 1 MiB per stream. The excess is counted and dropped, never
  hidden: read `dropped_bytes` and `truncated`. There is no flag to raise it --
  ask the remote command to `head` or `tail` instead.

## What the tool never does

- No subcommands for specific operations. To see processes send `ps`; for logs
  send `tail`. The tool does not know what nginx or a migration is.
- No judgement about whether a service is healthy or a deploy succeeded.
- No business inventory. Profile descriptions are free-text hints, never
  authoritative: ask the host with a command.
- No deploy, build, migration or database operation presets.
- No port forwarding, SOCKS, SFTP session, X11 forwarding or `--ssh-arg`
  pass-through.
- No `~/.ssh/config` reading: the invocation runs with `-F none`, so a user's
  `ProxyJump`/`LocalCommand` cannot silently apply. `known_hosts` and default
  identity files still work.

Host key verification is mandatory and has no bypass. An unknown host fails with
`host_key_untrusted`; establish trust deliberately:

```powershell
ssh-keyscan -t ed25519 10.0.0.11 >> $env:USERPROFILE\.ssh\known_hosts
```

## Errors and what to do

- `invalid_argument` (exit 1): fix the option or value.
- `profile_not_found` / `profile_conflict` (exit 1): run `profile list`, then set
  the intended name.
- `profile_registry_corrupt` / `profile_io` (exit 1): the registry file is
  unreadable or contended; inspect it rather than recreating blindly.
- `profile_invalid` (exit 1): a field failed validation (port range, negative
  rate); fix the value.
- `credential_store_unavailable` (exit 1): the OS keyring is unavailable; report
  it instead of retrying with a different target.
- `authentication_failed` (exit 1): the stored password is wrong or missing;
  `profile set-password` re-stores it.
- `host_key_untrusted` (exit 1): verify the fingerprint in `error.fingerprint`
  before changing anything. A changed key is more serious than an unknown one.
- `connection_failed` (exit 1): check the address, the network, and whether the
  host is up.
- `timeout` (exit 1): inspect the visible effect before repeating. `data` holds
  whatever output arrived, and `remote_state` is `unknown`, which means the remote
  process may still be running.
- `remote_nonzero_exit` / `remote_killed_by_signal`: read `data.stdout` and
  `data.stderr`; the remote program ran and failed.
- `dangerous_command` (exit 1): re-read the command and `danger_excerpts`; pass
  `--force` only after confirming the target. The audit line records the override.
- `read_only_violation` (exit 1): the profile is read-only. Mark it writable only
  if the machine genuinely must change.
- `approval_required` (exit 1): run `--request-approval` first, then pass the
  token with `--approve`.
- `rate_limited` (exit 1): wait for the sliding window; retrying immediately will
  also be refused.
- `internal_error` (exit 1): report it rather than guessing at recovery.

The process exit code is only 0 or 1, and is **not** the remote exit code. The
remote status is `data.remote_exit_code`, which is also truncated to eight bits by
the protocol: a remote `exit 256` arrives as `0`. Treat `success` as "the command
returned zero", not as "the intended outcome happened".

## Audit trail

Every attempt appends one JSON line to the local log, including refusals and dry
runs:

```text
%LOCALAPPDATA%\host-cli\host-cli\Logs\audit.jsonl
```

```powershell
host-cli audit summary                                 # counts by status and danger category
host-cli audit show --status blocked --limit 10        # recent refusals
host-cli audit show --status dry_run                   # recent probes
```

Each blocked entry carries a `reason` naming the gate that refused it, because a
read-only or approval refusal concerns a command the danger gate considered
perfectly safe.

Category counts are the useful observation: a rule that never fires may be
useless, and one that fires constantly is training the operator to pass `--force`
without reading.

Why this matters: the host itself usually cannot answer "what ran", because an
invocation without a pty writes no shell history, and sshd logs the login but never
the command.

## Additional resources

- [references/profiles.md](references/profiles.md) - profile fields, gate settings,
  credential storage, and the exact store locations.
