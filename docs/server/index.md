---
title: ZettCode server
---

# ZettCode server

`zettcode-server` puts the ZettCode coding agent behind an HTTP API. It runs the same agent as the terminal and the
SDK — same tools, plugins, MCP servers, skills, project instructions and session store — so a conversation begun over
HTTP can be reopened in the terminal, and the other way round.

It is a thin layer: every endpoint drives [`zettcode.sdk`](/sdk/), which drives the released `zett-agent` runtime. The
server owns no model loop, no tools and no session format of its own.

## Install and run

```bash
uv tool install zettcode
zettcode-server --workspace ~/projects/api --port 3290
```

One package, two commands: `uv tool install zettcode` writes the terminal's `zettcode` and this `zettcode-server`,
so the server is never a second install and always the same version as the agent.

```text
zettcode-server 0.1.11 · http://127.0.0.1:3290 · workspace /home/you/projects/api · permission deny · token off
```

The command binds **127.0.0.1** by default. Nothing is reachable from another machine until `--host` says so, and then
a token should say who may.

| Option | Meaning |
| --- | --- |
| `-w`, `--workspace DIR` | The directory the agent works in. One process serves one workspace, because the SDK keeps the process's working directory. |
| `--host`, `--port` | Where to listen; `127.0.0.1:3290` by default. |
| `--token` | A bearer token every endpoint but `/health` requires. Defaults to `$ZETTCODE_SERVER_TOKEN`. |
| `--permission {deny,ask,safe,full}` | The shell permission a run starts at; `deny` by default. `safe` runs every command in a sandbox that writes only the workspace and `/tmp`; `full` runs them with your own access. `auto`, the old name of `full`, is still taken. A client changes it per request. |
| `--harness` | Start with the just-in-time harness on: the model may write and run small Python tools. Off by default; `PATCH /settings` with `{"harness": true}` changes it. |
| `--model`, `--effort` | What the first run starts with. |
| `--config FILE` | A configuration file instead of `~/.zettcode/config.toml`. |
| `--log-level` | uvicorn's log level. |

::: warning One workspace, one process
A server serves the workspace it was started in. Running two workspaces in one process is a conflict, not a feature:
the agent's tools resolve paths against the process's working directory. Start a second server for a second project.
:::

## A fresh machine

The server starts **without any model configured**. `/health` says `ready: false`, `/models` is empty, and anything
that needs an agent answers `409 no_model` — while the model endpoints work, so the editor that is using the server
can set one up:

```bash
curl -X POST http://127.0.0.1:3290/models \
  -H 'content-type: application/json' \
  -d '{"model": "gpt-5-mini", "token": "sk-…", "display_model": "Fast"}'
```

The first model builds the agent; `/health` then says `ready: true`. The entry is written to the configuration file
with the same keys `/config add` uses, so the terminal sees it too. Add more, change one (the token is kept unless a new
one is given), or remove one — the last cannot go, because a configuration with no models is one no client can be made
from. `PATCH /settings {"model": "Fast"}` is how you choose among them, and the choice holds for the next prompt.

## A first request

```bash
curl http://127.0.0.1:3290/health
```

```json
{"status": "ok", "version": "0.1.0", "workspace": "/home/you/projects/api", "session": "01a15…", "busy": false}
```

Run a prompt and watch it:

```bash
curl -N -X POST http://127.0.0.1:3290/prompts \
  -H 'content-type: application/json' \
  -d '{"text": "summarize the README", "permissions": {}, "approvals": {"mode": "deny"}}'
```

```text
event: event
data: {"type":"text_delta","text":"The README describes"}

event: event
data: {"type":"tool_started","call_id":"call-1","name":"read_file","arguments":{"path":"README.md"}}

event: result
data: {"text":"The README describes …","session_id":"01a15…","usage":{…},"tools":[…],"stop":null}
```

[The event stream](/server/events) explains every frame; [the API reference](/server/api) lists every endpoint, and
the [TypeScript client](/server/typescript) wraps all of it for an editor or a Node program. The
[VS Code extension](https://github.com/Chang-LeHung/zettcode/tree/main/clients/vscode) is a complete editor face built
on that client: chained tool calls, clickable files, approvals and recent sessions.

## What a client can do

- **Run prompts** and stream their events; carry on an interrupted request where it stopped.
- **Answer the agent** while it runs: approve or deny a shell command, answer a question the model asked, or steer
  the request with a new instruction.
- **Manage sessions**: list, open, start, rename, fork, compact, export as a page, read the history.
- **Change the model, the reasoning effort and the permission level** between runs.
- **Measure**: token usage, the context report, the loaded plugins.

The interactive half is what makes the API a match for the terminal: a run that needs an answer is suspended, not
guessed. See [approvals and questions](/server/events#answering-a-run).

## Pointing a tool at it

The API is plain HTTP and JSON, so an editor extension, a CI job or a script speaks to it directly. Give it a token
when it is not loopback, and read the stream as `text/event-stream`:

```ts
const response = await fetch("http://127.0.0.1:3290/prompts", {
  method: "POST",
  headers: { "content-type": "application/json" },
  body: JSON.stringify({ text: "fix the failing test", approvals: { mode: "ask" } }),
});
const reader = response.body!.getReader();
// Each SSE block ends in a blank line; parse `event:` and `data:` from it.
```

## Security

- **Loopback by default**, so starting the server does not open a shell to the network.
- **`deny` by default** for shell commands: a prompt cannot run anything until it says how commands are answered.
- **A token is one line**: `--token` or `$ZETTCODE_SERVER_TOKEN`, compared in constant time, required by every endpoint
  but `/health`. It is a bearer token over plain HTTP, so use a tunnel or a reverse proxy that terminates TLS when the
  client is not on the same machine.
- **One run at a time in a conversation**: a second prompt while a run is going in the same conversation is refused
  with `409 busy` rather than interleaved. Another conversation is another run: starting or opening a session while one
  runs leaves the run going where it is, and `GET /sessions` says which sessions are running.
