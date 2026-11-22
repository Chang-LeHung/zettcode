# zettcode-ssh

Use ZettCode's conventional coding tools in a remote workspace, without installing or downloading
ZettCode on that machine.

```sh
pip install zettcode-ssh
```

In the terminal, select `/permission full`, then enter `/ssh` **without arguments** to open the SSH panel.
When `~/.ssh/config` has literal Host aliases, the panel first lists them for selection (Up/Down and Enter,
or click a host). Bounded `Include` files are supported; wildcard patterns are not offered as destinations.
Choose **Enter a host manually** for another host. The clearly bordered **Host** and **Remote workspace** fields
accept typing and pasting and show the editing caret. Fill the absolute remote path, then select
**Connect / apply remote target**. F2 reopens the host list; Tab selects fields/actions; Escape cancels.
Connection checks the remote workspace before changing the current target. Invalid fields, failed connections,
and cancellation leave the previous target unchanged. **Use local tools / disconnect** closes the channel and
returns to local tools. The panel shows the channel's current state and permission level.

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

- Local system **OpenSSH `ssh`**, configured authentication (an SSH agent or an accessible key), and an already
  verified host in `known_hosts`. Use ordinary SSH manually to verify an unknown host before using this plugin.
- Remote POSIX host with **Python 3.10+** and, for `bash`, `/bin/bash`. Python uses only its standard library.
- OpenSSH uses the reader's SSH config/authentication, with `BatchMode=yes`, `StrictHostKeyChecking=yes`, a
  ten-second connect timeout and no pseudo-terminal. The plugin never disables host verification, prompts for
  passwords, copies keys, exports credentials, or downloads ZettCode. One persistent SSH channel runs a standard-
  library Python worker through stdin/stdout; the worker never binds a network port or installs remote packages.
- **Every remote tool, including reads, requires the current permission `full`.** `ask`, `deny`, and `safe` are
  refused before starting SSH. The local safe sandbox does **not** constrain remote access. Per-command approval
  is not implemented; approving an ordinary local bash request cannot authorize this plugin. This deliberately
  conservative rule covers the remote Python interpreter as well as the command it executes.
- Remote paths have the user's remote filesystem access: absolute paths, `..`, and symlinks can leave the selected
  workspace. This is not a remote filesystem sandbox. Use a restricted remote account when confinement is needed.
- Host and path are the only inherited state. Request-scoped local daemon handoff variables are stripped from the
  local SSH subprocess environment; no handoff is encoded in the remote command or JSON. The reader's own OpenSSH
  `SendEnv` configuration remains theirs to audit for unrelated environment secrets.

## Tools and bounds

`read`, **`read_file`** (including text-only model substitution), `write_file`, `edit`, `bash`, `glob`, and `grep`
keep their usual names and are intercepted while SSH is selected. All relative paths and `bash.work_dir` are
remote. An SSH failure, missing Python, malformed response or permission refusal **never falls back locally**.
Only these conventional tools are redirected: local MCP tools, skills, project resources, and other plugin tools
are not made remote. JIT repository management and dynamic Python tools are unavailable while SSH is active:
their authoring paths and execution host are local. `read_tool_output` remains a bounded local reader restricted
to the current session's retained output folder, including after resume; it cannot read local workspace files.
The main agent receives explicit overriding remote context; local workspace instructions must not be treated as
the remote project's guidance. Read the remote `AGENTS.md` explicitly when relevant. Invalid SSH configuration
refuses startup rather than dropping the plugin and leaving local tools active.

- UTF-8 text reads: at most 2,000 lines and 50 KiB per call, numbered lines and continuation hints. Files are
  limited to 16 MiB; the maximum offset is 1,000,000. A single very long line returns a bounded prefix and a hint.
- `read` supports PNG/JPEG/GIF/WebP images up to 4 MiB. `read_file` is always text-only.
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
  configurable 1–600-second deadline (default 60, the same ceiling as the local tool), continuously drains output to
  a 50 KiB preview that keeps its start and its end, reports the remote exit code, and kills its process group on
  completion or timeout; the remote alarm follows that deadline instead of the fixed one. Cancellation kills and
  reaps the local SSH process. A lost SSH connection is not a guarantee of immediate remote termination; remote
  deadlines remain the backstop. Processes deliberately escaping their process group are not a supported daemon
  mechanism.

## Children and daemons

Each in-process child gets a fresh extension over a snapshot of the target and the **shared live permission
policy**, reusing the parent's channel. Requests on one channel are serialized and responses are matched by ID.
`explore` has only the reading side — `read`, `glob`, `grep`, plus `read_file` when the model takes text and not
pictures — `coding` may use all seven, `reasoning` has no tools.
Children replace their local filesystem bundle and local `AGENTS.md` extension; they receive remote environment
instructions instead. No local shell or write handler is left behind in an explore child.

The active **`Client.spawn_daemon` API** creates a *local* daemon with the selected SSH descriptor, restored before
plugin activation. The daemon needs this matching `zettcode-ssh` installed locally and uses its own permission
policy and establishes its own SSH channel. Only host/path are serialized, never the live connection.
Selecting local tools in the panel clears the target and closes the parent's owned channels.

Model `bash` is **remote**, so `zettcode daemon spawn` in that tool runs *on the remote host*, not locally. It would
require ZettCode and this matching plugin installed and configured there; no local daemon token, credentials or
inheritance handoff is sent remotely. Use the active client's spawn API for local inheriting daemons, not remote
bash. An independently started local CLI has no active client's runtime descriptor.

## Development

From this uv workspace: `make -C packages/zettcode-ssh test lint typecheck`, `uv build --package zettcode-ssh`.
Tests use mocked SSH processes and a temporary fake `ssh` executable to execute the fixed Python payload locally;
no network, remote credentials or real SSH server is needed.
