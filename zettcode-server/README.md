# zettcode-server

The ZettCode coding agent behind an HTTP API, in the same repository as the terminal program and its SDK.

One process serves one workspace. Every endpoint drives the released `zettcode` SDK — the same tools, plugins, MCP
servers, skills, project instructions and session store as the terminal — so a conversation begun here can be reopened
in `zettcode`, and the other way round. The package holds no agent of its own.

```bash
uv tool install zettcode-server
zettcode-server --workspace ~/projects/api
```

```text
zettcode-server 0.1.0 (zettcode 0.1.8) · http://127.0.0.1:3290 · workspace /home/you/projects/api · permission deny · token off
```

It binds loopback on port **3290**, denies shell commands by default, and asks for a bearer token only when one is
configured (`--token`, `$ZETTCODE_SERVER_TOKEN`).

A machine with no model configured is still served: `/health` says `ready: false` and `POST /models` writes the
`[[models]]` entry (the same one `/config add` writes) and builds the agent, so an editor can set ZettCode up without
touching a file by hand.

```bash
curl http://127.0.0.1:3290/health
curl -N -X POST http://127.0.0.1:3290/prompts \
  -H 'content-type: application/json' \
  -d '{"text": "summarize the README", "approvals": {"mode": "deny"}}'
```

The stream carries the run's events and ends with its result. A run that needs an answer — a shell command, a
question — is suspended and answered through `POST /runs/approvals` or `POST /runs/questions`, so a client stays in
the conversation instead of guessing.

- [The guide](https://chang-lehung.github.io/zettcode/server/): install, endpoints, event stream
- [TypeScript client](../clients/typescript): `npm install zettcode-client`
- [Python SDK](https://chang-lehung.github.io/zettcode/sdk/): the same agent from Python
