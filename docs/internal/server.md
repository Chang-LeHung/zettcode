# The HTTP server

`zettcode-server/` is the second member of the workspace. It is the same agent as the terminal, behind HTTP, and it
holds no agent of its own: `src/zettcode_server/app.py` maps endpoints onto `zettcode.sdk`, which maps them onto the
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
SDK run again — the run is genuinely suspended, not raced. `answer_timeout` bounds the wait, and a timeout applies the
default itself, so a client that vanishes cannot leave a tool call hanging.

A policy can also decide without the client: `deny`, `auto`, and `commands` answer inside the SDK's handler before the
frame is emitted, which is what makes an unattended run possible.

## The files

```
zettcode-server/src/zettcode_server/
  cli.py        zettcode-server: arguments, then uvicorn; --help imports neither FastAPI nor the agent
  app.py        create_app: endpoints, the SSE helper, the error mapping, the token check
  runner.py     the client, the one run, pending approvals and questions, steering, resuming
  schemas.py    the wire format: requests and responses, so the SDK may change without changing it
  serialize.py  SDK values and events into those schemas
  settings.py   the workspace, the socket, the token, the level a run starts at
```

The bundle test is `zettcode-server/tests/test_package.py`; behaviour is pinned by `test_api.py` (JSON endpoints,
auth, errors), `test_prompts.py` (the stream and the rules), `test_interaction.py` (answering, steering, resuming,
export), and `test_cli.py` (the command). `docs/internal/invariants.md` rows H1-H8 cite them.

## What is deliberately absent

- **The `/usage` ledger and the `/resume` table** (`app/agent/storage/ledger.py`, session stats) are not exposed: they
  are not in the SDK yet, and the server must not reach past it. Add a method to the SDK first.
- **Editing `config.toml`** (`/config`) is a terminal form, and the server reads its configuration at startup; write
  the file, restart, or pass `--model`/`--effort`.
- **Themes, pets, the status line** are the terminal's own.
- **WebSockets.** Not needed: the answer endpoints keep the stream one-way and the API plain HTTP.
