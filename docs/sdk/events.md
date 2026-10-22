---
title: Streaming events
---

# Streaming events

Iterating a run yields events as they happen. This page lists each one, shows how to match on them, and gives patterns for the things programs usually do with a stream: print progress, collect output, show a spinner, and log.

## The shape of an event

Every event is a frozen dataclass with a `session_id`. You match on the class and read fields that are always there. There is no `type` string to compare and no field that is sometimes missing.

```python
import zettcode.sdk as zc

async with client.prompt("fix the failing test") as run:
    async for event in run:
        match event:
            case zc.TextDelta(text=text):
                print(text, end="", flush=True)
            case zc.ToolStarted(name=name, arguments=arguments):
                print(f"\n→ {name} {arguments}")
            case zc.ToolFinished(name=name, ok=False, output=output):
                print(f"✗ {name}: {output[:200]}")
            case zc.Finished():
                print()
```

`match` needs Python 3.10, which is the minimum the project supports. `isinstance` works the same way if you prefer it.

## The events

The first seven are exported from `zettcode.sdk`; the rest live in `zettcode.sdk.events`.

| Event | Fields | When |
| --- | --- | --- |
| `TextDelta` | `text` | A piece of the answer. Joined, the deltas are the answer. |
| `ReasoningDelta` | `text` | A piece of the model's reasoning, for providers that report it. |
| `ToolStarted` | `call_id`, `name`, `arguments` | The model called a tool and it is starting. |
| `ToolFinished` | `call_id`, `name`, `output`, `ok`, `skipped` | A tool ended, in success, failure, or because it never ran. |
| `ApprovalRequested` | `call_id`, `command`, `timeout_seconds`, `remember_supported` | A shell command waits for your decision. |
| `QuestionAsked` | `call_id`, `question`, `options`, `allow_multiple` | The model asked you something. |
| `Finished` | `text` | The final answer is complete. |
| `UsageUpdated` | `usage` | The session's token totals after a model call. |
| `CompactionStarted` | — | The conversation is being summarized. |
| `CompactionFinished` | `applied`, `compaction` | A compaction ended. |
| `ModelStopped` | `reason`, `message` | A step ended for a reason other than finishing. |
| `Steered` | `text` | A message sent with `steer` reached the request. |
| `Notice` | `text`, `level` | News that is not part of the answer, such as an MCP server starting or one that could not be reached. `level` is `"info"` for progress and `"warn"` for something you may need to act on. |
| `RawEvent` | `event` | The underlying `zett-agent` event. Only with `raw=True`. |

`AnyEvent` is the union of all of them, for annotations:

```python
from zettcode.sdk.events import AnyEvent


def log(event: AnyEvent) -> None:
    print(type(event).__name__)
```

### Text and reasoning

```python
answer = []
async for event in run:
    if isinstance(event, zc.TextDelta):
        answer.append(event.text)
print("".join(answer))
```

`result.text` already has this, so assemble text yourself only to show it live. Empty deltas are never emitted.

### Tools

`ToolStarted` and `ToolFinished` pair on `call_id`. When the model makes several calls in one step, you get a `ToolStarted` for each and then a `ToolFinished` for each, so match on the id rather than assuming order.

```python
running: dict[str, str] = {}

async for event in run:
    if isinstance(event, zc.ToolStarted):
        running[event.call_id] = event.name
        print(f"⠋ {event.name}")
    elif isinstance(event, zc.ToolFinished):
        running.pop(event.call_id, None)
        mark = "✓" if event.ok else "–" if event.skipped else "✗"
        print(f"{mark} {event.name}")
```

`ok` is false for a failed call and for one that never ran; `skipped` is true only for the latter, when steering took over before the call began. `output` is what the tool returned, or the failure text.

A tool the model invents is a failed call with an explanatory `output`, not an exception.

### Approvals and questions

These two ask something of your program. The agent is suspended inside the tool call until they are answered. They are covered fully in [Approvals & questions](./approvals); in short:

```python
async for event in run:
    match event:
        case zc.ApprovalRequested() as ask:
            ask.approve() if ask.command.startswith("pytest") else ask.deny()
        case zc.QuestionAsked() as ask:
            ask.answer("yes") if ask.options else ask.decline()
```

Answer before asking the stream for its next event. A request still unanswered by then is denied or declined.

### Usage

`UsageUpdated.usage` is cumulative for the *session*, not for this run. Subtract a reading taken before the run for a delta, or read `result.usage` at the end.

```python
from zettcode.sdk.events import UsageUpdated

async for event in run:
    if isinstance(event, UsageUpdated):
        print(f"context {event.usage.context_tokens} tokens, {event.usage.requests} requests")
```

### Compaction

When the context fills, the agent summarizes older messages in the middle of a run.

```python
from zettcode.sdk.events import CompactionFinished, CompactionStarted

async for event in run:
    match event:
        case CompactionStarted():
            print("summarizing…")
        case CompactionFinished(applied=True, compaction=done):
            print(f"folded {done.compressed} messages; kept {done.kept}")
        case CompactionFinished(applied=False):
            print("nothing worth folding")
```

### Stops

`ModelStopped.reason` is one of `refusal`, `max_output`, `context_full`, `paused`, `interrupted`, `other`. The same value ends up in `result.stop`. The run keeps going where it can, so react in the stream only if you need to act at once.

## Patterns

### Print progress and a summary

```python
async def show(client, prompt):
    tools = 0
    async with client.prompt(prompt) as run:
        async for event in run:
            match event:
                case zc.TextDelta(text=text):
                    print(text, end="", flush=True)
                case zc.ToolStarted():
                    tools += 1
    print(f"\n\n{tools} tool calls, {run.result.usage.total_tokens} tokens")
    return run.result
```

### Fan out to several listeners with `on_event`

If the loop is not the right place to look at events, give the run a callback. The callback sees every event, including ones a handler answered.

```python
counts: dict[str, int] = {}


def count(event):
    counts[type(event).__name__] = counts.get(type(event).__name__, 0) + 1


result = await client.prompt("...", on_event=count)
print(counts)  # {'TextDelta': 41, 'ToolStarted': 3, 'ToolFinished': 3, 'Finished': 1, ...}
```

### Keep the whole stream

```python
result = await client.prompt("...", keep_events=True)
tool_events = [e for e in result.events if isinstance(e, zc.ToolStarted)]
```

`result.events` is empty unless you ask, because a long run produces many deltas.

### Time to first token

```python
import time

start = time.perf_counter()
first = None
async with client.prompt("...") as run:
    async for event in run:
        if isinstance(event, zc.TextDelta) and first is None:
            first = time.perf_counter() - start
print(f"first token after {first:.2f}s")
```

### Send events over the wire

Events are plain frozen dataclasses, so `dataclasses.fields` reads them. An answerable event also holds a private reply slot (`_reply`), which is not data; leave out any field whose name starts with an underscore. `RawEvent.event` is a `zett-agent` object, so skip it or convert it yourself.

```python
import dataclasses, json
from zettcode.sdk.events import RawEvent


def record(event) -> dict:
    fields = {f.name: getattr(event, f.name) for f in dataclasses.fields(event) if not f.name.startswith("_")}
    return {"type": type(event).__name__, **fields}


async for event in run:
    if not isinstance(event, RawEvent):
        await websocket.send(json.dumps(record(event), default=str))
```

`default=str` covers the `Usage` and `Compaction` values nested in `UsageUpdated` and `CompactionFinished`; use `dataclasses.asdict` on those if you want them as objects.

## Guarantees

- **Order within a call.** `ToolStarted` comes before the matching `ToolFinished`. `Finished` comes after the last `TextDelta` of the answer.
- **Nothing malformed reaches you.** A partly-formed custom event from an extension is dropped rather than raised, because a bad event must not fail a live request.
- **The stream ends.** When the loop finishes normally, `run.result` is set. When the run fails, the loop raises (see [Errors & timeouts](./errors)) and `run.result` stays `None`.
- **Every event carries a session id**, so one handler can serve several sessions.
