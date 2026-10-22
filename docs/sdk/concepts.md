---
title: Core concepts
---

# Core concepts

Five objects cover the whole SDK. Knowing what each one is for, and what it is not, makes the rest of the documentation short.

```text
Client ──────────────► one workspace, one configuration, one agent
  │
  ├── client.sessions ► Sessions: list / new / open / latest
  │
  └── client.session ─► Session: one stored conversation
                          │
                          └── session.prompt(...) ─► RunStream
                                                      │  await it  ─► RunResult
                                                      └─ iterate it ─► events
```

## Client

A `Client` is the agent for one workspace. It owns the configuration, the model connection, the plugin and MCP setup, the session store and the session lock. Make one, use it, close it.

```python
import zettcode.sdk as zc

async with zc.Client(".", permission="safe") as client:
    print(client.workspace)  # the resolved directory
    print(client.model.name)  # the active model
    print(client.permission)  # "safe"
```

A client is cheap to keep around and not cheap to create: making one loads the agent, reads the configuration and connects the extensions. Create one per program or per workspace, not one per prompt. For a single prompt, `zc.prompt()` does the whole lifecycle for you.

## Session

A `Session` is a handle on one stored conversation. The client always has a current one, `client.session`, and starts empty. Handles stay valid when the client works on another conversation; the next call that needs this one switches back.

```python
async with zc.Client(".") as client:
    session = client.session
    print(session.id)  # the identity you can resume later
    print(session.title)  # None until it has a name
    print(session.current)  # True: the next run would use this one
```

Sessions are stored on disk in the same format the terminal uses, so a conversation started here can be continued in the terminal with `/resume`, and the other way round.

## Run

A run is one request to the agent: you send a prompt, the model works, calls tools, and eventually answers. `session.prompt(...)` returns a `RunStream`, which is *both* things you may want from a run:

- **await** it for the finished `RunResult`;
- **iterate** it for the events as they happen.

```python
async with zc.Client(".") as client:
    result = await client.prompt("explain this module")  # wait for the end

    async with client.prompt("explain this module") as run:  # or watch it happen
        async for event in run:
            ...
```

You can also do both: iterate part of a run, then `await` it for the rest.

## Event

An event is one thing that happened during a run: a piece of text, a tool starting, a shell command waiting for approval. Events are frozen dataclasses, so you match on the class and read fields that are always there.

```python
async for event in run:
    match event:
        case zc.TextDelta(text=text):
            print(text, end="")
        case zc.ToolStarted(name=name, arguments=args):
            print(f"[{name}] {args}")
```

Two events ask something of your program: `ApprovalRequested` and `QuestionAsked`. The agent is suspended inside the tool call until they are answered, which is why they carry the methods that answer them. See [Approvals & questions](./approvals).

## Result

`RunResult` is the plain-data summary of a finished run: the answer, what was spent, which tools ran and how each ended, and why the model stopped if it did not finish normally.

```python
result = await client.prompt("run the tests")
result.text  # the answer
result.usage  # what this run spent (not the session's total)
result.tools  # every tool call, in order
result.failed_tools  # the ones that did not succeed
result.stop  # None, or "refusal", "max_output", ...
result.ok  # True exactly when stop is None
```

## The rules that follow from this

**One run at a time per client.** The terminal does one request at a time and so does a client. Starting a second run while one is in progress raises `SessionBusyError` instead of interleaving two requests in one conversation. For parallel work use one client per process; see [Errors & timeouts](./errors#parallel-work).

**One workspace per process.** The coding tools resolve relative paths against the process's working directory, which is global. Creating a client changes to the workspace, and closing the last one restores the original directory. A client on a second, different workspace raises `WorkspaceConflictError`.

**Close what you open.** `async with` closes the client, releasing the provider connection and the session lock. Use `async with client.prompt(...) as run:` whenever you may leave the loop early, so the run is closed even then.

**Nothing hangs.** An approval nobody answers is denied and a question nobody answers is declined, so a run without a handler cannot wait forever.

**Values are plain.** Everything the SDK returns is a frozen dataclass owned by the SDK. They can be built by hand in a test, compared, stored and printed.

## What the SDK shares with the terminal

| Shared | Meaning |
| --- | --- |
| Agent, tools, compaction | The same model loop; nothing is re-implemented. |
| Plugins, MCP servers, skills | Loaded from the same places, subject to the same settings. |
| `AGENTS.md` project instructions | Read when `agents_md_enabled` is on, which it is by default. |
| Session store | Same files and format; sessions move between code and terminal. |
| Permission levels | `deny`, `ask`, `safe`, `full` (`auto` is the old name of `full`), with the same meaning. |
| Config file | `~/.zettcode/config.toml`, unless you pass models or a config yourself. |

## What it switches off

A program embedding the agent should not do things behind its back, so a client defaults to `sessions_enabled=False` (no broker, so terminal sessions cannot message it) and `update_enabled=False` (no release check). Pass `sessions_enabled=True` to opt back in.

## Imports

`import zettcode.sdk` loads the package and nothing else. Names such as `Client` and `TextDelta` load their module on first use, and the agent loads when a `Client` is made. The package exports what a program uses every day; the rarer names are one import away in a submodule.

| Module | Holds |
| --- | --- |
| `zettcode.sdk` | `Client`, `Session`, `RunStream`, `prompt`, `prompt_sync`, `RunResult`, `Usage`, `Image`, the everyday events, the approval handlers, `ZettCodeError`, `ConfigurationError`, `RunError` |
| `zettcode.sdk.events` | Every event class, and `AnyEvent` for annotations |
| `zettcode.sdk.types` | `ModelInfo`, `SessionInfo`, `Message`, `ToolRecord`, `ContextReport`, `Compaction`, `ResumeInfo` and the other values methods return |
| `zettcode.sdk.errors` | Every error class |
| `zettcode.sdk.handlers` | `ApprovalHandler` and `QuestionHandler` for annotations |

```python
from zettcode.sdk.events import AnyEvent, Notice, Steered
from zettcode.sdk.types import ContextReport, ModelInfo
from zettcode.sdk.errors import NothingToDoError, SessionBusyError
```
