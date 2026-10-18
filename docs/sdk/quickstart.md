---
title: Quickstart
---

# Quickstart

Three examples that show what the SDK does and how to use it.

## One prompt

Send a prompt, get the result. The simplest way to call the agent.

```python
import zettcode.sdk as zc

result = await zc.prompt("summarize the README", workspace=".", permission="deny")
print(result.text)
print(f"Used {result.usage.total_tokens} tokens")
```

`permission="deny"` means no shell commands run, which suits an unattended script. The agent uses file tools instead.

### From sync code

```python
result = zc.prompt_sync("check the parser", workspace=".", permission="safe", timeout=120)
```

`prompt_sync()` blocks until done. It refuses to run inside an event loop where blocking would stall it.

## A conversation

A `Client` keeps the agent across prompts, so the conversation continues.

```python
async with zc.Client(".", permission="safe") as client:
    result = await client.prompt("make the tests pass")
    print(result.text)

    if not result.ok:
        print(f"Stopped: {result.stop}")

    followup = await client.prompt("explain what you changed")
    print(followup.text)
```

The second prompt sees what the first one did. `client.session.usage` is the session's total; `result.usage` is what that run spent.

## Streaming progress

Iterate the run to see events as they happen.

```python
async with zc.Client(".", permission="safe") as client:
    async with client.prompt("fix the bug") as run:
        async for event in run:
            match event:
                case zc.TextDelta(text=text):
                    print(text, end="", flush=True)
                case zc.ToolStarted(name=name):
                    print(f"\n[{name}]")
                case zc.ToolFinished(ok=False, output=output):
                    print(f"  Failed: {output}")

    print(f"\n{run.result.usage.total_tokens} tokens")
```

The run is both awaitable (gives the result) and async-iterable (gives the events). `run.result` is `None` until the run ends; after that it holds the `RunResult`.

## With approval rules

Shell commands need approval unless the permission level says otherwise. Pass a handler, answer events inline, or do neither and they are denied.

```python
def only_read_commands(request):
    return request.command.startswith(("git status", "git diff", "cat ", "ls "))

result = await client.prompt("check the diff", on_approval=only_read_commands)
```

or

```python
async with client.prompt("run the tests") as run:
    async for event in run:
        match event:
            case zc.ApprovalRequested() as ask:
                if "pytest" in ask.command:
                    ask.approve()
                else:
                    ask.deny()
            case zc.TextDelta(text=text):
                print(text, end="")
```

Built-in handlers:

- `zc.approve_all` — trust the workspace and the model
- `zc.deny_all` — no shell commands
- `zc.approve_commands("pytest", "git status")` — prefix matching, no shell syntax

## Sessions

Create, switch, and continue conversations.

```python
async with zc.Client(".") as client:
    # Start two conversations
    first = client.session
    await first.prompt("analyze the code")

    second = client.sessions.new()
    await second.prompt("write a test")

    # Back to the first
    await first.prompt("one more thing")

    # Continue a stored session
    stored = await client.sessions.open("abc123def")
    await stored.prompt("keep going")
```

`Client(resume="abc123def")` starts on a stored session. `client.sessions.list()` shows what the workspace has.

## What's next

- [**Core concepts**](./concepts) — how clients, sessions, and runs fit together
- [**Running prompts**](./running) — `prompt()`, `run()`, `stream()` and their arguments
- [**Events**](./events) — every event a run yields
- [**Sessions**](./sessions) — creating, forking, history, export
- [**Cookbook**](./cookbook) — complete examples
