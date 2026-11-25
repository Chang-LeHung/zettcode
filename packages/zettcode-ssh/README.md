# zettcode-ssh

Use ZettCode's conventional coding tools in a remote workspace, without installing or downloading
ZettCode on that machine.

```sh
pip install zettcode-ssh
```

In the terminal, select `/permission full`, then enter `/ssh` **without arguments** to open the SSH panel. It has
the shape of the other plugin panels: the title with the channel's state at the right, one row per thing, the
sentence the marked row does, and the keys.

```text
SSH                                                       ● connected · full

  ▸ Host        build-host-1         select or type a host
    Workspace   /srv/project         remote working directory
    User        (from config)        from ~/.ssh/config
    Sign in     ●───────── key/agent no password needed
    Password    (none needed)        not needed
    Connect     ↵ enter              check, then use it
    Disconnect  ↵ enter              close the remote channel

  Host: an alias from ~/.ssh/config, or user@hostname typed by hand
  ↑ ↓ row · ← → switch · F2 hosts · enter connect · esc cancel
```

When `~/.ssh/config` has literal Host aliases, the panel opens on them first (Up/Down and Enter, or a click).
Bounded `Include` files are supported; wildcard patterns are not offered as destinations, and `Enter a host
manually…` is always the last choice. F2 reopens that list. Typing and pasting edit the marked row, with a caret
where the next character goes; a password is painted as bullets.

**Both sign-ins are supported.** `Sign in: key/agent` is the no-password path: OpenSSH uses the key or the agent
from the reader's config, and nothing is asked; the knob sits on the left, and Right (or a click, or Space) slides
it to `password`. `Sign in: password` asks for the user's password; typing in the
password row selects it without a separate toggle. The password is handed to OpenSSH through a private `askpass`
helper (directory `0700`, file `0600`) and never appears in argv, environment values, logs, or a child's state;
it lives in memory for the session and is deleted when the channel closes. It is therefore not inherited by a
daemon: a target that needs one is retained but offers no remote tools, with a sentence explaining that a
headless daemon cannot enter a password. Reconnect in a terminal session or use key/agent authentication.

**Connect** checks the remote workspace before changing the target (with a 30-second limit, so an unreachable host
is reported rather than left turning); an invalid field, a wrong password, a failed
connection, and cancellation all leave the previous target unchanged. **Disconnect** closes the channel and
returns to local tools.

The `/ssh` command is terminal-only: it is not registered in VS Code or the HTTP client's plain command list.
Headless daemons can still restore an inherited target. A configuration can also select a target at startup,
connecting lazily on the first remote tool call:

```toml
[plugins.ssh]
host = "my-build-host"
path = "/srv/project"
```

Both keys are required together. Unknown keys, options masquerading as hosts, relative workspaces and malformed
inherited descriptors are refused. A daemon's inherited target takes precedence over the startup configuration.

## Requirements and security

- Local system **OpenSSH `ssh`** with an already verified host in `known_hosts`. Use ordinary SSH manually to verify
  an unknown host before using this plugin. Sign in with a key or the agent (no password), or with the account's
  password; password sign-in needs OpenSSH 8.4+ for `SSH_ASKPASS_REQUIRE=force`.
- Remote POSIX host with **Python 3.10+** and, for `bash`, `/bin/bash`. Python uses only its standard library.
- OpenSSH always uses `StrictHostKeyChecking=yes`, a ten-second connect timeout and no pseudo-terminal. Key/agent
  sign-in also uses `BatchMode=yes`; password sign-in uses `BatchMode=no`, one password prompt, and
  `PreferredAuthentications=password,keyboard-interactive`. Every server prompt is answered with the password, so
  a host that asks for a second factor (a one-time code) fails rather than waiting. The plugin never disables host
  verification, copies keys, exports credentials, or downloads ZettCode. One persistent SSH channel runs a
  standard-library Python worker through stdin/stdout; the worker never binds a network port or installs remote
  packages.
- **Every remote tool, including reads, requires the current permission `full`.** `ask`, `deny`, and `safe` are
  refused before starting SSH. The local safe sandbox does **not** constrain remote access. Per-command approval
  is not implemented; approving an ordinary local bash request cannot authorize this plugin. This deliberately
  conservative rule covers the remote Python interpreter as well as the command it executes.
- Remote paths have the user's remote filesystem access: absolute paths, `..`, and symlinks can leave the selected
  workspace. This is not a remote filesystem sandbox. Use a restricted remote account when confinement is needed.
- Host, remote path, user and sign-in method are the only inherited state; a password is never part of it.
  Request-scoped local daemon handoff variables are stripped from the
  local SSH subprocess environment; no handoff is encoded in the remote command or JSON. The reader's own OpenSSH
  `SendEnv` configuration remains theirs to audit for unrelated environment secrets. The askpass helper is removed
  when the channel closes and at process exit; only a process killed with `SIGKILL` can leave it, its directory
  `0700` and its file `0600`.

## Tools and bounds

Selecting a target **adds** remote tools; it replaces nothing, and the set mirrors what the local tools offer the
same session. `read`, `read_file`, `write_file`, `edit`, `bash`, `glob` and `grep` keep working on this machine.
On the selected host:

- a coding session (the main agent and the `coding` child) gets `ssh__read`, `ssh__write_file`, `ssh__edit` and
  `ssh__bash` — searching is the shell's job, exactly as it is locally, so there is no remote `glob`/`grep`;
- an `explore` child has no shell, so it gets `ssh__read`, `ssh__glob` and `ssh__grep`, and may not write or run;
- a `reasoning` child gets none of them;
- `ssh__read_file` replaces `ssh__read` for a model that cannot take a picture, and is never offered beside it.

All relative paths and `ssh__bash.work_dir` are remote; local tools never reach the host. Every remote action
requires the current permission `full`, and an SSH failure, missing Python, malformed response or permission
refusal is reported as it is, never retried as a local operation. The main agent receives a line saying which names
are remote; local workspace instructions still apply to local work, and the remote `AGENTS.md` is read explicitly
when it matters. An invalid SSH configuration does not stop the program: the plugin is reported as failed (on
`/plugins`) and the local tools simply stay as they are.

Those `ssh__` rows are drawn by the shell's own tool presenters: a presenter of this plugin only renames the row from
`ssh__read` to `read` before the chain draws it, so the colour, symbol, timer, fold and preview are the local tool's
and only the title keeps `ssh/` in the name. `ssh__` is reserved for this plugin: if an MCP server also produces one
of those names, adding the tools stops that request with a sentence naming the server to rename.

- UTF-8 text reads: at most 2,000 lines and 50 KiB per call, numbered lines and continuation hints. Files are
  limited to 16 MiB; the maximum offset is 1,000,000. A single very long line returns a bounded prefix and a hint.
- `ssh__read` supports PNG/JPEG/GIF/WebP images up to 4 MiB. `ssh__read_file` is always text-only.
- Writes are atomic replacements in the target directory; existing file modes are preserved. Edits match exact
  text (including original line endings), require one occurrence unless `replace_all=true`, and write nothing on
  a missing or ambiguous match. Concurrent external edits are not locked; read immediately before editing.
- Glob and grep results are bounded to 50 KiB and at most 5,000 entries (default 200). Glob sorts the bounded
  collected batch, not an unlimited tree. Grep accepts Python regular expressions, skips binary and oversized
  files, and limits each match preview to 2,000 bytes.
- Requests: 4 MiB JSON maximum; responses: 6 MiB maximum (including base64 images); SSH stderr: the first 16 KiB are retained and the remainder continuously drained.
  An interrupted request is not replayed; a later new request may reconnect. Closing or replacing the target
  permanently invalidates its old channels.
- Remote Python operations have a 125-second remote deadline and a 135-second local SSH deadline. `bash` has a
  configurable 0–120-second deadline (default 60), continuously drains output to a 50 KiB preview, reports the
  remote exit code, and kills its process group on completion or timeout. Cancellation kills and reaps the local
  SSH process. A lost SSH connection is not a guarantee of immediate remote termination; remote deadlines remain
  the backstop. Processes deliberately escaping their process group are not a supported daemon mechanism.

## Children and daemons

Each in-process child gets a fresh extension over a snapshot of the target and the **shared live permission
policy**, reusing the parent's channel. Requests on one channel are serialized and responses are matched by ID.
`explore` gets the remote read/search tools (`ssh__read`, `ssh__glob`, `ssh__grep`); `coding` gets the same set
its own local bundle has (`ssh__read`, `ssh__write_file`, `ssh__edit`, `ssh__bash`); `reasoning` gets none. A child
keeps its own local tools — nothing is replaced — and receives the line saying which names are remote.

The active **`Client.spawn_daemon` API** creates a *local* daemon with the selected SSH descriptor, restored before
plugin activation. The daemon needs this matching `zettcode-ssh` installed locally and uses its own permission
policy and establishes its own SSH channel. Only host, path, user and the sign-in method are serialized, never the
live connection and never a password.
Selecting local tools in the panel clears the target and closes the parent's owned channels.

Model `bash` is **remote**, so `zettcode daemon spawn` in that tool runs *on the remote host*, not locally. It would
require ZettCode and this matching plugin installed and configured there; no local daemon token, credentials or
inheritance handoff is sent remotely. Use the active client's spawn API for local inheriting daemons, not remote
bash. An independently started local CLI has no active client's runtime descriptor.

## Development

From this uv workspace: `make -C packages/zettcode-ssh test lint typecheck`, `uv build --package zettcode-ssh`.
Tests use mocked SSH processes and a temporary fake `ssh` executable to execute the fixed Python payload locally;
no network, remote credentials or real SSH server is needed. These are unit/fake-process checks, **not real SSH
acceptance**. Before release, run the checklist below against a disposable POSIX sshd and record OS, OpenSSH and
remote Python versions plus pass/fail evidence. Do not use production credentials or workspaces.

### Manual acceptance checklist (not yet executed by the unit suite)

- [ ] Verified `known_hosts`: connect with a configured key, then with ssh-agent only; read/write/edit a temporary
      remote project and verify local files are unchanged. Confirm one channel is reused across requests.
- [ ] Password: connect from the terminal panel with a correct password; reject an incorrect password and unsupported
      multi-factor prompt promptly, preserving the previous target. Verify password masking and helper cleanup.
- [ ] Host-key rejection: unknown and changed host keys must refuse, never auto-accept. Establish trust separately
      with ordinary SSH, then retry explicitly. Never disable verification to make this test pass.
- [ ] Real terminal PTY: open `/ssh`, choose Host with Enter/F2, type/paste fields, switch sign-in, connect/disconnect,
      resize/scroll, cancel a pending check with Escape/Ctrl-C, and confirm the prior target survives cancellation.
      SSH itself must remain non-PTY (`-T`).
- [ ] Permissions: full offers and runs remote tools; switching to safe/ask/deny removes them on the next request
      and refuses a previously offered handler. Restored password daemons retain the descriptor but offer no remote
      tools and explain that nobody can enter a password there; key/agent daemons work without terminal input.
- [ ] Large log: a >16 MiB text file supports a small late line range; a very long line has one bounded prefix and
      `line truncated` advice. Inspect transcript highlighting, line count, fold and resumed tool identity.
- [ ] Deadline/disconnect/no replay: run a long command with a short deadline and verify bounded output and group
      termination; interrupt a mutating request or sever its connection and check the unknown outcome warning.
      Confirm it is never replayed automatically; a later, explicitly new request may reconnect. Observe the remote
      deadline backstop after disconnect (disconnect alone does not guarantee immediate remote termination).
