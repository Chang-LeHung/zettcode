---
title: Sessions
---

# Sessions

A session is one stored conversation. This page covers finding them, switching between them, reading what they hold, and the operations on a conversation: rename, fork, export, compact, measure, and resume.

## The model

`client.session` is the current conversation. A new client starts with an empty one. `client.sessions` is the collection of what is stored for the workspace. A `Session` is a lightweight handle: it holds an id and asks the client to do the work.

```python
import zettcode.sdk as zc

async with zc.Client(".") as client:
    session = client.session
    print(session.id, session.title, session.current)
    print(session.path)         # the file the conversation is stored in
```

Sessions are written in the terminal's own format, in the same store. A conversation begun in code can be continued in the terminal with `/resume`, and one begun in the terminal can be continued here.

A session is written to disk when its first request is made. Until then it exists only in memory, which is why `history()` on a brand-new one raises `SessionNotFoundError`.

## Finding sessions

```python
async with zc.Client(".") as client:
    for info in await client.sessions.list(limit=10):
        print(info.id[:8], f"{info.updated_at:%Y-%m-%d %H:%M}", info.title or "(untitled)")
```

`list()` returns `SessionInfo(id, title, created_at, updated_at)`, most recently active first. `limit` defaults to 20 and must be a positive integer.

| Call | Does |
| --- | --- |
| `await client.sessions.list(limit=20)` | Lists the stored sessions of this workspace. |
| `client.sessions.new()` | Starts an empty conversation and makes it current. |
| `await client.sessions.open(id)` | Continues a stored conversation and makes it current. |
| `await client.sessions.latest()` | Continues the most recently active one, or returns `None`. |
| `Client(resume=id)` | Starts the client on a stored conversation. |

`open()` raises `SessionNotFoundError` for an id that does not exist, cannot be read, or would leave the store. It continues on the model the session last used, when the configuration still has it.

```python
async with zc.Client(".") as client:
    session = await client.sessions.latest()
    if session is None:
        session = client.session            # nothing stored; start fresh
    result = await session.prompt("where did we leave off?")
```

## Switching between conversations

Handles stay valid when the client moves to another conversation. The next call that needs a session makes it current again, with its own history and usage.

```python
async with zc.Client(".") as client:
    review = client.session
    await review.prompt("review the parser")

    feature = client.sessions.new()
    await feature.prompt("sketch a design for caching")

    await review.prompt("one more point on the parser")     # back to the first
    print(review.usage.total_tokens, feature.usage.total_tokens)
```

Switching is refused while a run is in progress, with `SessionBusyError`: a client runs one thing at a time.

## Reading history

```python
messages = await client.session.history()
for message in messages:
    print(f"{message.role:>9}: {message.text[:80]!r}")
```

`history()` returns the messages the model is working with: the compaction summary first if there is one, then what followed it. It does not include system messages or side questions, and a user message shows what the person typed, not the instructions an `@` reference added behind it. Reading takes no lock, so it works on a session another process has open.

| `Message` field | Meaning |
| --- | --- |
| `role` | `user`, `assistant` or `tool`. |
| `text` | What was said. |
| `tool_calls` | For an assistant message, a tuple of `ToolCallInfo(id, name, arguments)`. |
| `tool_call_id`, `tool_name`, `ok` | For a tool message, the call it answers, the tool, and whether it succeeded. |
| `images` | How many images the message carries. |

### Reconstructing what the agent did

```python
for message in await session.history():
    for call in message.tool_calls:
        print("called", call.name, call.arguments)
    if message.role == "tool" and not message.ok:
        print("failed:", message.tool_name, message.text[:120])
```

## Titles

```python
await session.rename("Parser refactor")             # returns the title as stored (trimmed)
title = await session.name_it()                     # asks the model, unless it already has one
print(session.title)
```

`rename` raises `ValueError` for a blank or over-long title. `name_it` leaves an existing title alone and returns `None` when there is no exchange yet to name.

## Forking

`fork()` copies the conversation's context into a new session and returns it. The original is left as it is, and the two do not affect each other.

```python
base = client.session
await base.prompt("read the project and tell me its structure")

attempt_a = await base.fork()
await attempt_a.prompt("refactor with dataclasses")

attempt_b = await base.fork()
await attempt_b.prompt("refactor with attrs")
```

This is the way to try two approaches from one understanding. The context the fork starts with is the one the model has, so a compacted conversation forks as compacted. Forking an empty session raises `SessionNotFoundError`.

## Exporting

```python
path = await session.export("reports/refactor.html")
print(path)                       # absolute path that was written
```

The conversation is written as a single HTML page rendered like the terminal shows it, with the request the next turn would send beside it. Without a path, the file is `zettcode-<id8>.html` in the workspace. A relative path is taken from the working directory, which is the workspace while a client is open. A session with nothing stored raises `ValueError`.

## Measuring the context

```python
report = await session.context()
if report is not None:
    print(f"{report.used:,} / {report.window:,} tokens ({report.fraction:.0%}), {report.free:,} free")
    for share in report.shares:
        print(f"  {share.name:<20} {share.tokens:>8,}  ({share.items} items)")
```

`context()` returns `None` before the first reply. The sources, in order, are `System prompt`, `Environment notes`, `Tool schemas`, `User messages`, `Assistant messages`, `Tool output` and `Compaction summary`; only non-empty ones appear.

| `ContextReport` field | Meaning |
| --- | --- |
| `window` | Tokens the model can carry. |
| `used` | Tokens the next request carries: the provider's own count when it gave one, else the tokenizer's. |
| `from_provider` | Whether `used` is the provider's count. |
| `measured_by` | The counter behind `shares`. |
| `partial` | `True` if a part could not be measured yet, so `used` reads low. |
| `free`, `fraction` | Derived: tokens left, and how full it is. |

### Compact before the window fills

```python
report = await session.context()
if report and report.fraction > 0.7:
    done = await session.compact()
    if done is not None:
        print(f"folded {done.compressed} messages into a summary, kept {done.kept}")
```

`compact()` summarizes the older part of the conversation now, without adding a turn. It returns a `Compaction(summary, compressed, kept)`, or `None` when there was nothing worth folding, and raises `NothingToDoError` when the conversation is already compacted to its newest message. The agent also compacts by itself at the model's `compact_percent`; a manual call is for when you want it earlier.

See [the context window](/guide/context) for what each source means.

## Resuming an interrupted request

A request can be cut short: a timeout, a crash, a lost connection, a Ctrl-C in the terminal. The conversation keeps everything up to that point, and the SDK can pick up where it stopped.

```python
info = await session.resumable()
if info is not None:
    print(info.kind, "-", info.description)
    result = await session.resume()
```

`resumable()` reads without writing and without calling the model. It returns `None` when the conversation was not interrupted. `ResumeInfo.kind` is one of:

| Kind | Meaning |
| --- | --- |
| `call_model` | The history is ready for the next model call; nothing is added. |
| `recover_tools` | Tools were running when it stopped. Each missing result is added saying the tool was interrupted and may or may not have run. **A tool is never run again on its own**, because nothing says whether its effect already happened. |
| `retry_response` | A response was cut off by a failure; the model is asked to start it again. |
| `continue_response` | A response reached the output limit; the model is asked to continue where it stopped. |

`resume()` waits for the result; `resume_stream()` returns a run you can iterate, with the same `on_approval`, `on_question`, `on_event`, `timeout` and `keep_events` arguments as `prompt`. Both raise `NothingToDoError` if there is nothing to pick up, with the reason.

### Retry a timed-out run

```python
from zettcode.sdk.errors import RunTimeoutError

try:
    result = await session.prompt("migrate the schema", timeout=300)
except RunTimeoutError:
    result = await session.resume(timeout=300)
```

## Locks

A session is locked by the process that has it open. Another process may read it, but not change it.

```python
if session.locked:
    print("open in another process; reading only")
    messages = await session.history()        # fine
else:
    await session.prompt("...")
```

Running, renaming, compacting and resuming on a locked session raise `SessionLockedError`. If the terminal is open on a conversation, the SDK can read it and cannot add to it, and the other way round.

## Self-compaction

Self-compaction is the model deciding when to compact its own context: the tool is offered when a request starts, and the model asks when it judges the detail is no longer needed. It has a configuration default (`[compaction] self`) and a choice per session. The terminal edits both in `/self-compact`; from code the session's choice is a property and a method:

```python
async with zc.Client(".") as client:
    print(client.self_compaction)          # whether it is in force for this session
    print(client.self_compaction_choice)   # True, False, or None to follow the default
    client.use_self_compaction(True)       # this session may compact itself
    client.use_self_compaction(None)       # follow the configuration again
```

The choice is written into the session, so it survives a restart; it applies from the next request, because the tool is offered when one starts. `OSError` means the choice could not be written, and the one in force is unchanged.

## What a session holds

`await client.session_stats()` is the stored side of a conversation: how many entries its file holds, how many replies it was charged for, and the tokens and cached share those replies cost. It is what the terminal's `/resume` columns show, and it reads a file only when it has changed. See [Usage and health](./usage).

```python
async with zc.Client(".") as client:
    for stats in await client.session_stats([client.session.id]):
        print(stats.entries, stats.input_tokens, stats.cache_share)
```

## Summary of the `Session` API

| Member | Kind | Does |
| --- | --- | --- |
| `id`, `title`, `usage`, `path`, `current`, `locked` | properties | Identity and state. |
| `prompt`, `stream`, `run` | methods | [Run a prompt](./running). |
| `ask(question)` | async | A side question that adds nothing to the conversation. |
| `steer(message)` | sync | Send a message to the request in progress. |
| `history()` | async | The messages the model works with. |
| `rename(title)`, `name_it()` | async | Give it a name. |
| `fork()` | async | Copy the context into a new session. |
| `export(path)` | async | Write an HTML page. |
| `context()`, `compact()` | async | Measure, and summarize now. |
| `resumable()`, `resume()`, `resume_stream()` | async / sync | Pick up an interrupted request. |
