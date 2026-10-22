---
title: Cookbook
---

# Cookbook

Complete programs for common jobs. Each uses only what the rest of this documentation describes, and each can be copied and run after changing the workspace and the model.

Unless a recipe says otherwise it assumes a config file with a model in it. To run without one, add `models=[{"model": "...", "token": os.environ["..."]}]` to the `Client(...)`; see [Client & configuration](./client#models-without-a-config-file).

## Fix the tests in CI

An unattended job: it may run the test suite and read git state, nothing else, and it must finish.

```python
import asyncio
import sys

import zettcode.sdk as zc
from zettcode.sdk.errors import RunError, ZettCodeError

RULE = zc.approve_commands("pytest", "git status", "git diff")


async def main() -> int:
    try:
        async with zc.Client(".", permission="safe", ask_user_enabled=False) as client:
            result = await client.prompt(
                "The tests fail. Find out why and fix the source, not the tests. Run pytest to check.",
                on_approval=RULE,
                timeout=900,
            )
    except RunError as error:
        print(f"agent failed (retryable={error.retryable}): {error}", file=sys.stderr)
        return 2
    except ZettCodeError as error:
        print(f"could not start: {error}", file=sys.stderr)
        return 3

    print(result.text)
    print(f"\n{result.usage.total_tokens:,} tokens, {len(result.tools)} tool calls", file=sys.stderr)
    return 0 if result.ok else 1


sys.exit(asyncio.run(main()))
```

The exit codes tell the pipeline whether the agent failed to run (2), could not start (3), or stopped without finishing (1). The `safe` level already lets harmless commands through, and anything outside the rule is denied rather than waited for.

## An interactive terminal assistant

Live output, a confirmation prompt for shell commands, and a conversation that carries on.

```python
import asyncio

import zettcode.sdk as zc


async def confirm(request: zc.ApprovalRequested) -> bool:
    answer = await asyncio.to_thread(input, f"\n  run `{request.command}`? [y/N] ")
    return answer.strip().lower() == "y"


async def answer(question: zc.QuestionAsked) -> str | None:
    options = f" ({' / '.join(question.options)})" if question.options else ""
    text = await asyncio.to_thread(input, f"\n  ? {question.question}{options}: ")
    return text or None


async def main() -> None:
    async with zc.Client(".", permission="ask") as client:
        while True:
            text = (await asyncio.to_thread(input, "\n> ")).strip()
            if text in {"", "exit", "quit"}:
                break
            async with client.prompt(text, on_approval=confirm, on_question=answer) as run:
                async for event in run:
                    match event:
                        case zc.TextDelta(text=chunk):
                            print(chunk, end="", flush=True)
                        case zc.ToolStarted(name=name):
                            print(f"\n  [{name}]", end="")
            print(f"\n  ({run.result.usage.total_tokens:,} tokens; session {client.usage.total_tokens:,})")


asyncio.run(main())
```

`input()` runs in a thread so the event loop stays free. A blank answer to a question returns `None`, so it is declined and the model moves on.

## A token budget

Stop a run that is spending more than you intended. `UsageUpdated` carries the session's running totals, so subtract the reading from before the run.

```python
import zettcode.sdk as zc
from zettcode.sdk.events import UsageUpdated


class BudgetExceeded(Exception):
    pass


async def prompt_within(client: zc.Client, text: str, *, budget: int) -> zc.RunResult:
    start = client.usage.total_tokens
    async with client.prompt(text) as run:
        async for event in run:
            if isinstance(event, UsageUpdated) and event.usage.total_tokens - start > budget:
                raise BudgetExceeded(f"more than {budget:,} tokens")
    assert run.result is not None
    return run.result
```

Leaving the `async with` closes the run, so the client is free again. What the run had added to the conversation stays; use `resume()` if you decide to let it finish.

## Triage with one model, fix with another

Use a cheap, fast model to decide whether a task is worth the expensive one.

```python
import zettcode.sdk as zc

MODELS = [
    {"model": "small-fast-model", "token": "...", "display_model": "fast"},
    {"model": "large-strong-model", "token": "...", "display_model": "strong", "context_window": 400_000},
]


async def handle(issue: str) -> str:
    async with zc.Client(".", models=MODELS, permission="deny") as client:
        client.use_model("fast")
        client.use_effort("low")
        triage = await client.prompt(
            f"Reply with exactly one word, SIMPLE or HARD: how hard is this change?\n\n{issue}"
        )
        if "HARD" in triage.text.upper():
            client.use_model("strong")
            client.use_effort("high")
        fix = await client.prompt(f"Implement this change:\n\n{issue}")
        return fix.text
```

The conversation carries across the switch, so the stronger model sees the triage. Use `display_model` to give each entry a name that `use_model` accepts when two share a model id. A level the model does not take raises `ConfigurationError` and lists the ones it does.

## Compare two approaches with a fork

Build one understanding of the project, then try two designs from it.

```python
import zettcode.sdk as zc


async def compare(client: zc.Client, task: str, approaches: list[str]) -> dict[str, str]:
    base = client.session
    await base.prompt("Read the project and summarize how it is organized. Do not change anything.")

    results: dict[str, str] = {}
    for approach in approaches:
        attempt = await base.fork()
        result = await attempt.prompt(
            f"{task}\n\nApproach: {approach}. Describe the diff you would make, but make no edits."
        )
        results[approach] = result.text
    return results
```

The forks start from the same context and do not affect each other. They run one after another on the one client; for true parallelism use [separate processes](./errors#parallel-work).

## Review every changed file

A batch job, with a fresh conversation per file so one file's context does not crowd the next, and a summary of what it cost.

```python
import subprocess
from pathlib import Path

import zettcode.sdk as zc


async def review_changes() -> None:
    changed = subprocess.run(
        ["git", "diff", "--name-only", "origin/main"], capture_output=True, text=True, check=True
    ).stdout.split()

    total = zc.Usage()
    async with zc.Client(".", permission="deny", ask_user_enabled=False) as client:
        for name in changed:
            if not name.endswith(".py"):
                continue
            session = client.sessions.new()
            result = await session.prompt(
                f"Review {name} for bugs and unclear code. List only real problems, one line each.",
                timeout=180,
            )
            print(f"## {name}\n{result.text}\n")
            total = zc.Usage(
                input_tokens=total.input_tokens + result.usage.input_tokens,
                output_tokens=total.output_tokens + result.usage.output_tokens,
            )
    print(f"{total.total_tokens:,} tokens for {len(changed)} files")
```

`permission="deny"` means the model reads and reasons but never runs a command. The model reads each file with its own file tools.

## Ask about a screenshot

```python
import zettcode.sdk as zc


async def explain_screenshot(path: str) -> str:
    async with zc.Client(".", permission="deny", model="vision") as client:
        if not client.model.multimodal:
            raise SystemExit(f"{client.model.name} cannot read images")
        result = await client.prompt(
            ["This is the page as a user sees it. What is wrong with the layout? ", zc.Image.from_path(path)]
        )
        return result.text
```

Check `client.model.multimodal` first for a clear message; a model that cannot read images would raise `ConfigurationError` before anything is sent.

## Get structured data back

The model returns text. Ask for JSON, and validate it yourself.

```python
import json

import zettcode.sdk as zc


async def list_todos(client: zc.Client) -> list[dict]:
    result = await client.prompt(
        "Find every TODO comment in the source tree. Reply with only a JSON array of "
        '{"file": str, "line": int, "text": str} objects, no prose, no code fence.'
    )
    text = result.text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    items = json.loads(text)
    if not isinstance(items, list):
        raise ValueError("expected a JSON array")
    return [item for item in items if isinstance(item, dict) and {"file", "line", "text"} <= item.keys()]
```

When the reply does not parse, send a second prompt that quotes the error and asks again; the conversation already holds the first attempt.

## Serve a run over a WebSocket

Send each event to a browser as it happens. This uses Starlette; any framework with async handlers is the same shape.

```python
import dataclasses
import json

from starlette.websockets import WebSocket

import zettcode.sdk as zc
from zettcode.sdk.events import RawEvent


def encode(event) -> str:
    fields = {f.name: getattr(event, f.name) for f in dataclasses.fields(event) if not f.name.startswith("_")}
    return json.dumps({"type": type(event).__name__, **fields}, default=str)


async def chat(websocket: WebSocket, client: zc.Client) -> None:
    await websocket.accept()
    async for message in websocket.iter_text():
        async with client.prompt(message) as run:
            async for event in run:
                if isinstance(event, zc.ApprovalRequested):
                    await websocket.send_text(encode(event))
                    reply = json.loads(await websocket.receive_text())
                    event.approve() if reply.get("approve") is True else event.deny()
                elif not isinstance(event, RawEvent):
                    await websocket.send_text(encode(event))
```

One client serves one browser at a time. A server with several users needs a client per user, in a process per workspace.

## Testing code that uses the SDK

Keep a test off the network and off your real sessions: a temporary store, no extensions that read outside the workspace, and a fake model.

With `pytest-asyncio`, set `asyncio_mode = "auto"` in your pytest configuration so an `async` fixture is run by the plugin; in its default strict mode the fixture below is not awaited and the test fails.

```python
import pytest

import zettcode.sdk as zc


@pytest.fixture
async def client(tmp_path):
    async with zc.Client(
        tmp_path,
        models=[{"model": "test-model", "token": "unused"}],
        store=tmp_path / "sessions",
        mcp_enabled=False,
        skills_enabled=False,
        agents_md_enabled=False,
        plugins_enabled=False,
    ) as client:
        yield client
```

For the model, replace what the runtime builds for a provider with a scripted one. The SDK's own tests do this; see `tests/sdk_helpers.py` in the repository for a small `ScriptedModel` and a `wire` helper that you can copy.

To test your approval handlers, build an event by hand and call the handler:

```python
def test_only_pytest_is_allowed():
    rule = zc.approve_commands("pytest")
    assert rule(zc.ApprovalRequested("s", "c", "pytest -q")) is True
    assert rule(zc.ApprovalRequested("s", "c", "pytest; rm -rf ~")) is False
```

## Continue tomorrow

```python
import zettcode.sdk as zc


async def today(client: zc.Client) -> str:
    result = await client.prompt("Start migrating the settings module to dataclasses.")
    return result.session_id  # save it


async def tomorrow(session_id: str) -> None:
    async with zc.Client(".", resume=session_id) as client:
        info = await client.session.resumable()
        if info:
            await client.session.resume()
        else:
            await client.prompt("Carry on with the migration.")
```

The same id works in the terminal: `/resume` and pick it, or start it from the session list.

## A pre-commit review

```python
import subprocess
import sys

import zettcode.sdk as zc


def main() -> int:
    diff = subprocess.run(["git", "diff", "--cached"], capture_output=True, text=True, check=True).stdout
    if not diff.strip():
        return 0
    result = zc.prompt_sync(
        f"Review this staged diff. If you see a real bug, start your reply with BLOCK, otherwise OK.\n\n{diff}",
        workspace=".",
        permission="deny",
        timeout=120,
        ask_user_enabled=False,
    )
    print(result.text)
    return 1 if result.text.lstrip().upper().startswith("BLOCK") else 0


sys.exit(main())
```

`prompt_sync` is what a script that is not async wants: it runs the loop itself, and with `permission="deny"` there is nothing to approve.
