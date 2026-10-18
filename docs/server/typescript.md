---
title: TypeScript client
---

# TypeScript client

`zettcode-client` is the TypeScript client for the server. It has no runtime dependency, needs Node 20+ (or any host
with `fetch`), and covers the whole API: prompts streamed as they run, sessions, models, approvals, questions,
steering, cancelling and continuing.

```bash
npm install zettcode-client
```

## A run

```ts
import { ZettCodeClient } from "zettcode-client";

const client = new ZettCodeClient({ baseUrl: "http://127.0.0.1:3290", token: process.env.ZETTCODE_TOKEN });

const run = client.prompt("fix the failing test", {
  approvals: { mode: "ask" },
  onApproval: async (request) => confirm(`Run ${request.command}?`),
});

for await (const frame of run) {
  if (frame.event === "event" && frame.data.type === "text_delta") {
    append(frame.data.text);
  }
}
const result = await run.result;
```

`run` is an async iterable of frames and carries a `result` promise. Either can be used without the other: the frames
are queued as they arrive, so `await run.result` alone is the non-streaming form, and iterating after the result is
known replays what arrived.

## Answering

The server suspends a run that needs an answer. The client can answer through handlers, which post the answer before
the stream continues:

```ts
client.prompt("make the tests pass", {
  approvals: { mode: "ask" },
  questions: "ask",
  onApproval: (request) => request.command.startsWith("pytest"),
  onQuestion: (request) => request.options[0] ?? null,   // null declines
});
```

or by hand, by `call_id`:

```ts
await run.approve("call-1", true);       // or run.approve(callId, false)
await run.answer("q-1", "sqlite");
await run.steer("also update the docs");
await run.cancel();
```

`client.runState()` says what is going and what it waits on, which is how an editor that reloaded can show the
question again.

## The rest of the API

| Client | Endpoint |
| --- | --- |
| `health()` | `GET /health` |
| `models()`, `settings()`, `updateSettings(change)`, `plugins()` | `/models`, `/settings`, `/plugins` |
| `listSessions(limit)`, `createSession(title?)`, `currentSession()` | `/sessions`, `/sessions/current` |
| `openSession(id)`, `renameSession(title)`, `nameSession()`, `forkSession()` | `/sessions/...` |
| `compactSession()`, `context()`, `history()`, `exportSession()`, `ask(question)` | `/sessions/current/...` |
| `usage()`, `usageLedger()`, `sessionStats(ids?)` | `/usage`, `/usage/ledger`, `/sessions/.../stats` |
| `selfCompaction()`, `setSelfCompaction(choice)`, `mentions(query)`, `doctor(timeout)` | `/sessions/current/self-compaction`, `/mentions`, `/doctor` |
| `prompt(text, options)`, `resume(options)` | `POST /prompts`, `POST /runs/resume` |
| `runState()`, `resumable()`, `approve()`, `answer()`, `steer()`, `cancelRun()` | `/runs/...` |

## Errors

- `ZettCodeError` — an HTTP failure: `code` (`busy`, `not_found`, `invalid`, …), `status`, and the server's message.
- `RunFailedError` — the run failed after its stream opened.
- `RunCancelledError` — the run was stopped by `cancel()`, `abort()`, or the server.

## Where it lives

The client is in [`clients/typescript`](https://github.com/Chang-LeHung/zettcode/tree/main/clients/typescript) in the
same repository, next to the server it speaks to. Run its tests with `make client`; they compile the sources and talk
to a real local HTTP server, split SSE chunks included.
