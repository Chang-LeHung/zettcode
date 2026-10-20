---
title: TypeScript client
---

# TypeScript client

`zettcode-client` is the TypeScript client for [`zettcode-server`](/server/): the coding agent behind HTTP, driven from
Node, a VS Code extension, or anything with `fetch`. It has no runtime dependency, needs Node 20+ (or any host with
`fetch`), and covers the whole API — prompts streamed as they run, sessions, models, approvals, questions, steering,
cancelling, usage and the event stream.

```bash
npm install zettcode-client
```

The package is in [`clients/typescript`](https://github.com/Chang-LeHung/zettcode/tree/main/clients/typescript) in the
same repository, beside the server it speaks to. The [VS Code extension](/vscode/) bundles its sources directly, so the
chat there and your own program share one wire client.

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
known replays nothing.

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

## Images and history

A prompt carries pictures for a model that takes them, and the history gives them back, so a client that reopens a
session can show what was attached:

```ts
await client.prompt("what is wrong here?", {
  images: [{ data: base64Png, mediaType: "image/png" }],
});

const messages = await client.history({ full: true });
for (const message of messages) {
  for (const picture of message.pictures ?? []) {
    show(`data:${picture.media_type};base64,${picture.data}`);
  }
  if (message.images > (message.pictures?.length ?? 0)) {
    show(`${message.images} more images, not stored`);
  }
}
```

`history()` is what the model works from; `history({ full: true })` is the whole conversation as it was written, with
each compaction summary where it was made as a `summary` message.

## Setting a model up

A server with no model configured still answers, so the editor can create one:

```ts
const health = await client.health();      // { ready: false, models: 0, session: null, … }
if (!health.ready) {
  await client.addModel({ model: "gpt-5-mini", token: apiKey, display_model: "Fast" });
}
await client.updateModel("Fast", { context_window: 200_000 });   // the token is kept
await client.updateSettings({ model: "Fast" });                  // choose it for the next prompt
await client.updateSettings({ compact_percent: 70 });            // summarize at 70% of the window
```

`addModel` writes the same `[[models]]` entry `/config add` writes; `removeModel` refuses the last one. A setting that
could not be written to the file comes back in `unsaved`, and holds for this run only.

## The rest of the API

| Client | Endpoint |
| --- | --- |
| `health()` | `GET /health` |
| `models()`, `addModel(entry)`, `updateModel(name, changes)`, `removeModel(name)` | `/models`, `/models/{name}` |
| `settings()`, `updateSettings(change)`, `plugins()` | `/settings`, `/plugins` |
| `listSessions(limit)`, `createSession(title?)`, `currentSession()` | `/sessions`, `/sessions/current` |
| `openSession(id)`, `renameSession(title)`, `nameSession()`, `forkSession()` | `/sessions/...` |
| `compactSession()`, `context()`, `history({full})`, `exportSession()`, `ask(question)`, `askStream(question)` | `/sessions/current/...` |
| `usage()`, `usageLedger()`, `sessionStats(ids?)` | `/usage`, `/usage/ledger`, `/sessions/.../stats` |
| `selfCompaction()`, `setSelfCompaction(choice)`, `mentions(query)`, `doctor(timeout)` | `/sessions/current/self-compaction`, `/mentions`, `/doctor` |
| `prompt(text, options)`, `resume(options)` | `POST /prompts`, `POST /runs/resume` |
| `runState()`, `resumable()`, `approve()`, `answer()`, `steer()`, `cancelRun()` | `/runs/...` |

## Errors

- `ZettCodeError` — an HTTP failure: `code` (`busy`, `not_found`, `invalid`, …), `status`, and the server's message.
- `RunFailedError` — the run failed after its stream opened.
- `RunCancelledError` — the run was stopped by `cancel()`, `abort()`, or the server.

## Tests

`make client` compiles the sources and runs the suite against a real local HTTP server, split SSE chunks included.
