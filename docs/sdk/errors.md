---
title: Errors & timeouts
---

# Errors & timeouts

Everything the SDK raises on purpose derives from `ZettCodeError`, so one `except` can mean "ZettCode refused or failed". This page lists what raises what and when, how to retry, how timeouts work, and how to run things in parallel.

## The hierarchy

```text
Exception
└── ZettCodeError
    ├── ConfigurationError        (also ValueError)
    ├── ClientClosedError
    ├── SessionBusyError
    ├── SessionLockedError
    ├── SessionNotFoundError      (also LookupError)
    ├── NothingToDoError
    ├── WorkspaceConflictError
    ├── DaemonStartError
    ├── SendError
    └── RunError
        └── RunTimeoutError       (also TimeoutError)
```

`ZettCodeError`, `ConfigurationError` and `RunError` are exported from `zettcode.sdk`. The rest are in `zettcode.sdk.errors`.

```python
from zettcode.sdk.errors import SessionBusyError, SessionNotFoundError
```

Three of them also inherit the built-in a caller would already be catching, so existing handlers keep working: `except ValueError` catches a `ConfigurationError`, `except LookupError` a `SessionNotFoundError`, and `except TimeoutError` a `RunTimeoutError`.

Where there was an underlying error, it is kept as `__cause__`.

## Reference

| Error | Raised when | Typical response |
| --- | --- | --- |
| `ConfigurationError` | An unknown setting (with a suggestion), a model, effort or permission that does not exist, a model entry that is malformed, a missing token, a workspace that is not a directory, or images sent to a model that cannot read them. | Fix the code or the config. Not retryable. |
| `ClientClosedError` | Any use of a client after `aclose()`. | Make a new client. |
| `SessionBusyError` | A run, a switch, a fork or a rename is attempted while a run is in progress. | Wait for the run, close it, or use another process. |
| `SessionLockedError` | Another process has the session open and you tried to run, rename, compact or resume. | Read-only access works; wait or fork. |
| `SessionNotFoundError` | A session id that does not exist or cannot be read; `history()` or `fork()` on a session with no messages yet. | Check the id with `sessions.list()`. |
| `NothingToDoError` | `resume()` on a conversation that was not interrupted, or `compact()` on one already compacted. The message says why. | Not a failure; skip. |
| `WorkspaceConflictError` | A client on a different directory is open in this process. | Close the first, or use a separate process. |
| `DaemonStartError` | `daemons.spawn_daemon()` started a process that never became reachable. `log` names the file with its first words. | Read the log; usually no model is configured. |
| `SendError` | `send()` could not reach anyone. `reason` says why: `offline` (no broker), `lost` (the connection ended with the message in flight), or the broker's own (`unknown`, `ambiguous`, `rejected`, `timeout`, `loop`, `rate`, `empty`, `too_long`). | Look at `reason`; `ambiguous` wants the session id instead of the handle. |
| `RunError` | The model, the provider or the network failed during a run. | Look at `retryable`. |
| `RunTimeoutError` | A run outlasted its `timeout`. | `resume()`, or retry. |

Invalid *arguments* are the built-in errors: `ValueError` for an empty prompt, a non-positive `timeout` or `limit`, a bad image or a blank title; `TypeError` for a prompt that is not text and images, or a handler that returns the wrong kind of thing.

## Where an error appears

A call that **returns a run** (`prompt`, `stream`, `resume_stream`) checks its arguments at once and raises for a bad one there. Everything that touches the model raises when you **await or iterate** the run:

```python
run = client.prompt("")  # ValueError raised here
run = client.prompt("explain this")  # nothing has happened yet
result = await run  # RunError, RunTimeoutError, ... raised here
```

So wrap the `await` or the `async for`, not the call that creates the run:

```python
from zettcode.sdk.errors import RunError

try:
    result = await client.prompt("...")
except RunError as error:
    ...
```

## Run failures

A failure of the model, the provider or the network raises `RunError`:

| Attribute | Meaning |
| --- | --- |
| `str(error)` | A readable description of what went wrong. |
| `error.retryable` | Whether trying again could succeed: a timeout, a dropped connection, a rate limit, a server error. A rejected key or a malformed request is **not**. |
| `error.partial_text` | What the model had already said when the error came. Often still worth keeping. |
| `error.__cause__` | The original exception from the provider library. |

```python
try:
    result = await client.prompt("summarize the changelog")
except RunError as error:
    print("failed:", error)
    if error.partial_text:
        print("partial answer:", error.partial_text)
```

A refusal or a cut-off is **not** an error. The model answered, so it is a `RunResult` whose `stop` says why. See [Running prompts](./running#a-run-that-did-not-simply-finish).

### After a failure

The client is free again, and the conversation keeps everything the run had added to it. A failed run has no `result`: `run.result` stays `None`. Send another prompt, or `resume()` the interrupted one.

## Retrying

Retry only when `retryable` is true, with a delay that grows, and a limit.

```python
import asyncio
import random
from zettcode.sdk.errors import RunError


async def prompt_with_retry(client, text, *, attempts=4, **options):
    delay = 2.0
    for attempt in range(1, attempts + 1):
        try:
            return await client.prompt(text, **options)
        except RunError as error:
            if not error.retryable or attempt == attempts:
                raise
            await asyncio.sleep(delay + random.uniform(0, delay / 4))
            delay *= 2
```

This sends the prompt again as a new turn, so the model sees the earlier attempt's partial work. Use `resume()` to continue the interrupted request instead, which is better when tools had already run:

```python
async def finish(session, text, *, attempts=3):
    try:
        return await session.prompt(text)
    except RunError:
        for _ in range(attempts):
            try:
                if await session.resumable() is None:
                    break
                return await session.resume()
            except RunError as error:
                if not error.retryable:
                    raise
        raise
```

::: tip
The agent library already retries transient provider errors (three extra attempts by default, with growing delays) before you see one. A `RunError` that arrives here has been retried; do not stack a large retry loop on top of it.
:::

## Timeouts

`timeout=` bounds a **whole run** in seconds, not each event.

```python
from zettcode.sdk.errors import RunTimeoutError

try:
    result = await client.prompt("run the integration suite", timeout=300)
except RunTimeoutError as error:
    print(f"gave up after {error.seconds:g}s")
    print(error.partial_text)
```

When the deadline passes, the run is stopped and `RunTimeoutError` is raised. It is a `RunError` (with `retryable=True`) and also a `TimeoutError`. The conversation keeps what the run had added, so `await session.resume()` can carry on.

`timeout` must be a positive number (a bool does not count) or `None`, which waits as long as it takes; anything else raises `ValueError` before the run starts.

The deadline is measured from when the run starts, and is checked while waiting for each event, so a model stuck in the middle of a step is stopped on time, and a slow consumer of the stream does not extend it.

### Cancelling from outside

You can also stop a run by cancelling the task that awaits it:

```python
task = asyncio.create_task(client.run("long job"))
await asyncio.sleep(30)
task.cancel()
try:
    await task
except asyncio.CancelledError:
    pass
```

Cancellation is never wrapped or swallowed: `CancelledError` propagates untouched. The run is closed and the client is free again.

For a deadline that covers several steps, use `asyncio.timeout` (Python 3.11+) or `asyncio.wait_for` around the whole sequence.

## Parallel work

A client runs one thing at a time. Starting a second run while one is in progress raises `SessionBusyError`, rather than interleaving two requests in one conversation.

```python
from zettcode.sdk.errors import SessionBusyError

async with client.prompt("first") as run:
    async for event in run:
        try:
            client.prompt("second")
        except SessionBusyError as error:
            print(error)
        break
```

Two requests can be made at once in different ways:

- **Different processes**, one client each. This is the supported way to run work in parallel, and it is the only way to work in two workspaces at once. Use `concurrent.futures.ProcessPoolExecutor`, `multiprocessing`, or a job runner, and call `prompt_sync` or `asyncio.run` in the worker.
- **Different sessions in turn**: `sessions.new()` and `fork()` give independent conversations, but they still take turns on the one client.

```python
import asyncio
from concurrent.futures import ProcessPoolExecutor
import zettcode.sdk as zc


def review(path: str) -> str:
    return zc.prompt_sync(f"review {path}", workspace=".", permission="deny", timeout=300).text


if __name__ == "__main__":
    with ProcessPoolExecutor(4) as pool:
        for text in pool.map(review, ["src/a.py", "src/b.py", "src/c.py"]):
            print(text)
```

The `if __name__ == "__main__":` guard is required wherever processes are started by spawning (macOS and Windows): each worker imports this file again, and without the guard it would start a pool of its own and the pool breaks with `BrokenProcessPool`.

Workers each load the agent; that is the setup cost to weigh against what a review takes. Point them at the same `store`: sessions are separate files.

## Closing under a reader

Closing a client while another task is reading a run ends that task's loop cleanly rather than raising: its events are simply over.

```python
async def reader(run):
    async for event in run:
        ...  # ends when the client closes


task = asyncio.create_task(reader(client.prompt("...")))
await asyncio.sleep(5)
await client.aclose()
await task  # returns; no error
```

## Errors you should not catch

- `asyncio.CancelledError` is the caller's. Do not catch it without re-raising.
- A bug in a handler (`on_approval`, `on_question`, `on_event`) reaches the caller **unchanged**, not as a `RunError`. The command it was deciding is denied first.

## A defensive wrapper

```python
from zettcode.sdk.errors import (
    ConfigurationError,
    RunError,
    SessionLockedError,
    ZettCodeError,
)


async def safe_prompt(client, text, **options):
    try:
        return await client.prompt(text, **options)
    except ConfigurationError:
        raise  # a bug in how it is called: let it fail loudly
    except SessionLockedError:
        return None  # someone else has the session
    except RunError as error:
        log.warning("run failed (retryable=%s): %s", error.retryable, error)
        return None
    except ZettCodeError as error:
        log.error("ZettCode refused: %s", error)
        raise
```
