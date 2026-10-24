# zettcode-client

The TypeScript client for [`zettcode-server`](../../docs/server/index.md): the ZettCode coding agent behind HTTP, driven
from Node, a VS Code extension, or anything with `fetch`.

It is one dependency-free module: the JSON endpoints, a real server-sent-events parser, and a `Run` that streams one
prompt while letting you answer it — approve a shell command, answer a question, steer the request, cancel it.

```bash
npm install zettcode-client
```

## Run a prompt

```ts
import { ZettCodeClient } from "zettcode-client";

const client = new ZettCodeClient({ baseUrl: "http://127.0.0.1:3290", token: process.env.ZETTCODE_TOKEN });

const run = client.prompt("fix the failing test", {
  approvals: { mode: "ask" },
  onApproval: async (request) => {
    const yes = await askInTheEditor(`Run \`${request.command}\`?`);
    return yes;
  },
});

for await (const frame of run) {
  if (frame.event === "event" && frame.data.type === "text_delta") {
    appendToTheEditor(frame.data.text);
  }
}
const result = await run.result;      // also available without iterating: the frames are queued
console.log(result.text, result.usage.input_tokens);
```

The stream and the result are independent: iterate `run`, await `run.result`, or both. Iterating after the result is
known replays nothing — the queue is drained in order as it arrives.

## Answering a run

A run that needs an answer is suspended on the server, not guessed. The client has two levels:

```ts
// 1. Handlers: called for each request, and the answer is posted before the stream continues.
const run = client.prompt("make the tests pass", {
  approvals: { mode: "ask" },
  questions: "ask",
  onApproval: (request) => request.command.startsWith("pytest"),
  onQuestion: (request) => request.options[0] ?? null,      // null declines
});

// 2. Manual: answer a request by its call_id, from wherever you are.
await run.approve("call-1", true, /* remember */ true);
await run.answer("q-1", "sqlite");
await run.steer("also update the docs");
await run.cancel();
```

`GET /runs/current` is `client.runState()`: whether a run is going and what it waits on, so an editor that reloads
can show the pending request again.

## Sessions

```ts
const sessions = await client.sessions.list({ limit: 20 });
await client.sessions.open(sessions[0].id);
await client.session.rename("Pagination work");
const forked = await client.session.fork();
const page = await client.session.export();         // standalone HTML
const messages = await client.session.history();
const answer = await client.session.ask("what changed?");   // beside the conversation, not in it
```

The names are the Python SDK's, in camelCase, and `client.sessions` / `client.session` are grouped the way
`zettcode.sdk` groups them. Where the two differ it is because TypeScript talks to a server: `session.info()` reads
what Python reads as properties, and `sessions.open(id)` returns the session's data rather than a handle.

## Models and settings

```ts
const { models, current } = await client.models();
await client.updateSettings({ model: "fast", effort: "low", permission: "safe" });
```

## Usage, mentions and health

```ts
const ledger = await client.usageLedger();          // by session, model and day
const rows = await client.sessionStats();           // one row of the terminal's /resume
const files = await client.mentions("cli");         // the @ completion menu
const checks = await client.checkModels();          // which configured models answer
await client.useSelfCompaction(true);               // or false, or null for the configuration default
```

## Continuing an interrupted request

```ts
const state = await client.session.resumable();
if (state.resumable) {
  const run = client.session.resume({ approvals: { mode: "deny" } });
  console.log((await run.result).text);
}
```

## Images and mentions

```ts
const run = client.prompt("what is wrong in this screenshot?", {
  images: [{ data: buffer.toString("base64"), mediaType: "image/png" }],
  mentions: true,     // resolve @path, as the terminal does
});
```

## Errors

- `ZettCodeError` — an HTTP failure, with `code` (`busy`, `not_found`, …) and `status`.
- `RunFailedError` — the run failed after the stream opened; the server's sentence is the message.
- `RunCancelledError` — the run was stopped by `cancel()`, by `abort()`, or by the server.

## Cancelling and closing

`run.cancel()` asks the server to stop the run, which ends the stream with `cancelled`. `run.abort()` closes the
connection instead; the server treats that as a stop too. An `AbortSignal` passed in `prompt(text, { signal })` does the
same.

## Tests and build

```bash
npm install
npm test          # builds, then runs the client against a real HTTP server, including split SSE chunks
npm run build     # dist/src, with declarations
```

The tests start a local server and speak the API over a socket: no model, no provider, no network.
