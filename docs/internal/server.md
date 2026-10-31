# The HTTP server

`zettcode/src/zettcode/server/` is the HTTP face of the package. It is the same agent as the terminal, behind HTTP,
and it holds no agent of its own: `app.py` maps endpoints onto `zettcode.sdk`, which maps them onto the
released `zett-agent` runtime. A bug in tools, compaction, sessions or message types is never fixed there; the SDK is
the place to add what the server needs. `AGENTS.md` states the rule.

## Why one workspace per process

The SDK keeps one conversation per client and the process's working directory *is* the workspace: the file tools
resolve relative paths against it, and two clients for different workspaces in one process raise
`WorkspaceConflictError`. The server does not fight that. `Settings.workspace` is fixed at startup, `Runner` builds one
`Client`, and a second project is a second process (and a second port).

## Why SSE plus answer endpoints

A prompt is one HTTP request whose body streams the run. The terminal's other half is *answering* the run: shell
approvals, `ask_user` questions, steering. SSE is one-way, so the answers come back as ordinary requests:

```
POST /prompts  ──── event: approval_requested ────▶  client
      ▲                                               │
      │  the run is suspended inside the tool call     │ POST /runs/approvals
      └──────────── the stream continues ◀────────────┘
```

The suspension point matters. The SDK yields the `ApprovalRequested` event and applies its default (deny) only when
the next event is asked for. `Runner.stream` therefore yields the frame, then awaits the answer *before* iterating the
SDK run again — the run is genuinely suspended, not raced. `answer_timeout` bounds an approval's wait, and a timeout
denies it itself, so a client that vanishes cannot leave a command hanging. A question has no deadline: it waits for
`POST /runs/questions` as long as the reader takes, and cancelling the stream is how a run stops waiting.

A policy can also decide without the client: `deny`, `auto`, and `commands` answer inside the SDK's handler before the
frame is emitted, which is what makes an unattended run possible.

## The files

```
zettcode/src/zettcode/server/
  cli.py        zettcode-server: arguments, then uvicorn; --help imports neither FastAPI nor the agent
  app.py        create_app: endpoints, the SSE helper, the error mapping, the token check
  runner.py     the client, the one run, pending approvals and questions, steering, resuming
  schemas.py    the wire format: requests and responses, so the SDK may change without changing it
  serialize.py  SDK values and events into those schemas
  settings.py   the workspace, the socket, the token, the level a run starts at
```

The server is a subpackage, not a second distribution: one `pip install zettcode` writes both console scripts and
`zettcode-server --version` reports the package's one version. The bundle test is `test_server_package.py`; behaviour
is pinned by `test_server_api.py` (JSON endpoints, auth, errors), `test_server_prompts.py` (the stream and the rules),
`test_server_interaction.py` (answering, steering, resuming, export), and `test_server_cli.py` (the command).
`docs/internal/invariants.md` rows H1-H8 cite them.

## Messages from other sessions

`Runner` holds one `Slot` per open conversation — its own SDK client, run lock, pending answer and inbox — and one of
them is *current*: the one a prompt, an answer and `GET /messages` mean. Opening or starting a session while the current
one runs does not wait for it and does not stop it: the running slot is put aside, a client made like it (the same
model, effort, permission and harness) opens the other conversation, and `GET /sessions` marks the aside one
`running`. Opening a running session again makes its slot current as it is. A slot that is neither current nor running
is closed (`_tidy`, after every run), so only what is running costs a client. The SDK still allows one conversation and
one run per client, which is why this is several clients and not one client with several runs, and why a model change
is refused while a run is going in the current conversation: the client the run uses is edited in place, not rebuilt.

## Messages from other sessions

The server is a session, not a reader of the broker's list: `Runner` builds its client with `sessions_enabled=True`
and hands it :meth:`Client.join_sessions`, so a terminal (or another editor) can address this chat and a message sent
to it arrives here. A message that asks to `steer` is handed to the run in progress when there is one — framed for
the model, and not listed in the inbox; the run reports it when it adopts it (`Steered`), and one it never reads
goes back to the inbox when the run ends (`_recover_steered`) rather than being lost. Holding the rest instead of
running them at once is what lets the editor draw the turn: the server keeps what arrives (`GET /messages` lists it,
oldest first, at most 16) and the extension answers each with `POST /messages/{id}`, which streams the turn in the
same frames as `/prompts`. The model reads the message framed with who sent it, and the sender hears back only if
the model calls `send_message`; the answer is this chat's own.

Sending is the other direction. An `@name` in a draft is resolved by the SDK when the prompt is run, exactly as in
the terminal: the model reads `session "name"` and the instructions for reaching it, and sends with its tool. The
server also exposes an explicit send, `POST /sessions/current/send` (`{to, text, mode?}`, answered with who took it
and what it will do — `started`, `steered` or `queued`; `mode` defaults to `steer`), for a program that means to
send without a model turn; nobody to reach is a `404 unreachable`, not a failure of the server. A `send_message`
the model makes is a tool row like any other, but its card opens by itself and shows the message above the delivery
line.

## What is deliberately absent

- **The `/usage` ledger and the `/resume` table** (`engine/storage/ledger.py`, session stats) are not exposed: they
  are not in the SDK yet, and the server must not reach past it. Add a method to the SDK first.
- **Editing `config.toml`** (`/config`) is a terminal form, and the server reads its configuration at startup; write
  the file, restart, or pass `--model`/`--effort`.
- **Themes, pets, the status line** are the terminal's own.
- **WebSockets.** Not needed: the answer endpoints keep the stream one-way and the API plain HTTP.
