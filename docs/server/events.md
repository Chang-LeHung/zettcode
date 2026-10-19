---
title: The event stream
---

# The event stream

`POST /prompts` and `POST /runs/resume` answer `text/event-stream`: the run's events as they happen, then one terminal
frame. Each frame is a name and one JSON line:

```text
event: event
data: {"type":"text_delta","text":"Added pagination to "}

event: event
data: {"type":"tool_started","call_id":"call-1","name":"replace_in_file","arguments":{"path":"src/users.py"}}

event: result
data: {"text":"Added pagination …","session_id":"01a15…","usage":{…},"tools":[…],"stop":null}
```

A blank line ends a frame. The stream closes after its terminal frame. Three names occur:

| Event | Payload | Meaning |
| --- | --- | --- |
| `event` | one of the types below | Something happened during the run. |
| `result` | a run result | The model finished; this is what a non-streaming client would have returned. |
| `error` | `{"error","message"}` | The run failed after the stream opened. |
| `cancelled` | `{"type":"cancelled"}` | The run was stopped (`/runs/cancel`, or the connection closed). |

## The events

| `type` | Fields | Meaning |
| --- | --- | --- |
| `text_delta` | `text` | A piece of the answer; append. |
| `reasoning_delta` | `text` | A piece of the model's reasoning, for the providers that report it. |
| `tool_started` | `call_id`, `name`, `arguments` | A tool call began. |
| `tool_finished` | `call_id`, `name`, `output`, `ok`, `skipped` | It ended, in success or failure; `skipped` when steering took over. |
| `approval_requested` | `call_id`, `command`, `approved` | The model wants to run a shell command. See below. |
| `question_asked` | `call_id`, `question`, `options`, `allow_multiple`, `answered` | The model asked something. |
| `usage_updated` | `usage` | The session's totals after a model call. |
| `compaction_started` | — | The conversation is being summarized. |
| `compaction_finished` | `applied`, `summary` | It ended. |
| `model_stopped` | `reason`, `message` | A step stopped for something other than finishing: `refusal`, `max_output`, `context_full`, `paused`, `interrupted`, `other`. |
| `steered` | `text` | A message sent with `/runs/steer` reached the running request. |
| `notice` | `text`, `level` | News that is not part of the answer, such as an MCP server starting or down, or an answer that timed out. `level` is `"info"` for progress and `"warn"` for something you may need to act on; a frame without one is progress. |
| `finished` | `text` | The run's last event before its result. |
| `event` | `name` | An event this server does not know; kept rather than dropped, so a newer SDK does not look like silence. |

## Answering a run

A run that needs an answer is **suspended**, not guessed. With `approvals.mode: "ask"` a shell command arrives as an
`approval_requested` frame and the run waits; with `questions: "ask"` a question arrives as `question_asked` and the run
waits. The answer is a second request, which is what lets a client with one connection still drive both directions:

```bash
# terminal A: the stream stops after this frame
event: event
data: {"type":"approval_requested","call_id":"call-1","command":"pytest -q","approved":null}

# terminal B: the answer
curl -X POST http://127.0.0.1:3290/runs/approvals \
  -H 'content-type: application/json' \
  -d '{"call_id": "call-1", "approve": true, "remember": true}'
```

```json
{"resolved": true}
```

- `answer` a question with `POST /runs/questions` `{"call_id": "...", "answer": "sqlite"}`; `null` declines it.
- `resolved` is `false` when the run is not waiting on that call — because it was already answered, or it timed out.
- Each waits at most `answer_timeout` seconds (300 by default) and then takes the safe default: the command is denied,
  the question is declined, and a `notice` frame says so. A client that crashes cannot hang a run.
- `GET /runs/current` says what is waiting, so a reconnecting client can show the request again:

```json
{"running": true, "pending": {"kind": "approval", "call_id": "call-1", "command": "pytest -q", "remember_supported": true}}
```

The `approved` field of the frame is `null` because the frame asks the question; the answer is the POST's. With
`deny`, `auto` or `commands`, the rule answers before the frame is sent and `approved` is `true` or `false`.

## Steering, stopping, continuing

| Call | Effect |
| --- | --- |
| `POST /runs/steer` `{"text": "also update the docs"}` | The run drops what it is doing and takes the message into account. `{"steered": false}` when nothing is running. |
| `POST /runs/cancel` | Stops the run; its stream ends with `cancelled`. Closing the connection does the same. |
| `GET /runs/resumable` | `{"resumable": true, "kind": "error", "description": "The provider dropped the connection"}` when a request was interrupted. |
| `POST /runs/resume` | Continues it, streaming exactly like `/prompts`. `409 nothing_to_do` when there is nothing to pick up. |

## A client loop

```ts
const response = await fetch(`${base}/prompts`, {
  method: "POST",
  headers: { "content-type": "application/json", authorization: `Bearer ${token}` },
  body: JSON.stringify({ text, approvals: { mode: "ask" }, questions: "ask" }),
});
for await (const frame of frames(response.body!)) {
  switch (frame.event) {
    case "event":
      handleEvent(frame.data);
      if (frame.data.type === "approval_requested") {
        const approve = await askTheUser(frame.data.command);   // a dialog in the editor
        await fetch(`${base}/runs/approvals`, {
          method: "POST",
          headers: { "content-type": "application/json", authorization: `Bearer ${token}` },
          body: JSON.stringify({ call_id: frame.data.call_id, approve }),
        });
      }
      break;
    case "result":
      return frame.data;
    case "error":
      throw new Error(frame.data.message);
  }
}
```

`frames` is SSE parsing: split on a blank line, take the `event:` name and join the `data:` lines. Nothing here needs
a browser, so a Node extension reads the same stream with `response.body` as an async iterable.
