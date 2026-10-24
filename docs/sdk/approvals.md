---
title: Approvals & questions
---

# Approvals & questions

An agent that can run shell commands and ask questions has to be able to wait for an answer. This page covers the two things it can wait for, the three ways to answer, the built-in rules, and how to write your own safely.

## What the agent waits for

| Event | The agent is waiting for… | If nobody answers |
| --- | --- | --- |
| `ApprovalRequested` | …a decision on a shell command. | The command is **denied**; the model is told and carries on. |
| `QuestionAsked` | …an answer to a question from the `ask_user` tool. | The question is **declined**; the model is told you cancelled. |

The agent is suspended *inside the tool call* until one of these is settled. That is why a run with no rule for them still cannot hang: anything unanswered by the time the stream is asked for its next event is denied or declined.

Approvals only arise at the `ask` [permission level](./client#permission-levels). At `deny` nothing runs and nothing is asked; at `safe` every command runs, unasked, inside an operating-system sandbox; at `full` everything runs and nothing is asked.

## Three ways to answer

### 1. A handler

Pass a function or a coroutine function to the run. It is called before the event reaches your loop, and its return value is the answer.

```python
import zettcode.sdk as zc


def only_tests(request: zc.ApprovalRequested) -> bool:
    return request.command.startswith("pytest")


result = await client.prompt("make the tests pass", on_approval=only_tests)
```

An approval handler returns:

| Return | Meaning |
| --- | --- |
| `True` | Approve. |
| `False` | Deny. |
| `None` | I'm not deciding; leave the request alone (it can still be answered in the loop, and is denied if not). |

A question handler returns text to answer with, or `None` to leave it.

```python
async def ask_a_person(question: zc.QuestionAsked) -> str | None:
    return await my_ui.prompt(question.question, choices=question.options)


result = await client.prompt("set up the project", on_question=ask_a_person)
```

A handler may be async. A blank string leaves the question unanswered, and so does `None`.

### 2. Answer in the loop

When you are iterating anyway, answer on the event:

```python
async with client.prompt("deploy to staging") as run:
    async for event in run:
        match event:
            case zc.ApprovalRequested(command=command) as ask:
                if input(f"run {command!r}? [y/N] ").lower() == "y":
                    ask.approve()
                else:
                    ask.deny()
            case zc.QuestionAsked(question=question, options=options) as ask:
                ask.answer(input(f"{question} {options or ''} "))
            case zc.TextDelta(text=text):
                print(text, end="")
```

On an approval: `approve()`, `approve(remember=True)`, `deny()`. On a question: `answer("text")` and `decline()`. Answer before asking the stream for its next event, unless the run was started with `defer_answers=True` (see below).

`input()` blocks the event loop here. That is fine for a script and wrong for a server; use `await asyncio.to_thread(input, ...)` or your UI's async prompt there.

### Answering later, from somewhere else

A program with a panel or a chat asks its reader in a different place from the loop that reads events, and the reader
answers when they answer. Start the run with `defer_answers=True` and the request is left open past its event: show it
from a handler that returns `None`, and settle it when the reader has chosen, with the event's own `approve()`, `deny()`,
`answer()` or `decline()`. The agent stays suspended in the tool call until then. Whatever is still open when the run
ends (it finished, was stopped, or failed) is denied or declined, so nothing is left waiting on a run that is over.

```python
async with client.prompt("deploy it", on_approval=panel.show, defer_answers=True) as run:
    async for event in run:
        ...                      # panel.show(request) returned at once; panel calls request.approve() later
```

### 3. Do neither

Unanswered means denied and declined. An unattended job can rely on this.

```python
result = await client.prompt("clean up the build directory")  # shell requests are denied
```

You may combine them: a handler answers the commands it recognizes and returns `None` for the rest, and the loop deals with what remains.

## Built-in rules

| Handler | Behaviour |
| --- | --- |
| `zc.approve_all` | Approves every command. Only for a workspace and a model you would trust with a shell. |
| `zc.deny_all` | Denies every command. The model is told and continues. |
| `zc.approve_commands(*commands)` | Approves a listed command, or one that continues a listed command with arguments. Denies everything else. |

```python
rule = zc.approve_commands("pytest", "git status", "git diff", "ruff check")

result = await client.prompt("fix the lint errors and run the tests", on_approval=rule)
```

### What `approve_commands` matches

A command matches when it **is** one of the listed commands or **continues one with a space**:

| Rule | Command | Matches |
| --- | --- | --- |
| `git status` | `git status` | ✓ |
| `git status` | `git status -s` | ✓ |
| `git status` | `git statusx` | ✗ |
| `pytest` | `pytest tests/ -k parser` | ✓ |
| `pytest` | `python -m pytest` | ✗ |

Leading and trailing space is ignored, on the rule and on the command.

### Why shell syntax never matches

A prefix rule alone would approve `git status; rm -rf ~`, because it starts with `git status`. So a command containing any of these characters is **never** matched, however it starts:

```text
;  &  |  <  >  $  `  (  )  {  }  \  and newlines
```

That excludes pipelines, chaining, redirection, substitution and subshells. If you need `pytest | tail`, either approve the plain `pytest` and let the model read the full output, or write a handler of your own that parses the command.

The same check applies to the rules you write. A rule containing a shell character, or a blank one, raises `ValueError` when you make the handler, not when a command arrives:

```python
zc.approve_commands("git status; ls")  # ValueError: 'git status; ls' holds a shell character; ...
zc.approve_commands("   ")  # ValueError: A command to allow cannot be blank
```

## Writing your own rule

A handler sees an `ApprovalRequested` with:

| Field | Meaning |
| --- | --- |
| `command` | The command the model wants to run. |
| `timeout_seconds` | The limit it would run under, when the tool states one. |
| `remember_supported` | Whether approving can be remembered for the rest of the run. |
| `call_id`, `session_id` | The tool call and the session. |

### An allow-list with a log

```python
import logging

log = logging.getLogger("agent.shell")
ALLOWED = zc.approve_commands("pytest", "ruff check", "git diff")


def audited(request: zc.ApprovalRequested) -> bool:
    allowed = ALLOWED(request)
    log.info("%s %s", "ALLOW" if allowed else "DENY", request.command)
    return allowed
```

### A rule that asks a person for anything unknown

```python
async def human_in_the_loop(request: zc.ApprovalRequested) -> bool | None:
    if ALLOWED(request):
        return True
    return await chat.confirm(f"The agent wants to run:\n\n{request.command}")
```

### Remembering a decision

`approve(remember=True)` lets the same kind of command run unasked for the rest of the run, when `remember_supported` is true. Asking to remember something that cannot be remembered is not an error; it approves once.

```python
async for event in run:
    match event:
        case zc.ApprovalRequested(command=command, remember_supported=True) as ask if command.startswith("npm test"):
            ask.approve(remember=True)
```

### Mistakes it refuses to make

A handler must return exactly `True`, `False` or `None`. Anything else raises `TypeError`, **without approving**, because the likeliest wrong value is a truthy string such as `"no"`, and approving a shell command by accident is the worst way to be wrong.

```python
def careless(request):
    return "no"  # TypeError: An approval handler returns True, False or None, not str
```

If a handler raises, the command is denied, the run stops, and the error reaches the caller of `await` unchanged. A bug in a rule does not leave a command running.

A question handler must return text or `None`; anything else is a `TypeError`.

## Answering twice

The first answer wins and is sent exactly once. Answering the same way again is harmless. Answering the opposite raises `ValueError`, because the agent has already acted on the first.

```python
ask.approve()
ask.approve()  # fine
ask.deny()  # ValueError: Already answered ...
```

`ask.answered` tells you whether it was settled, by you or by the run's handler, and `ask.approved` is `True`, `False` or `None` while unanswered.

An event the SDK did not create has nothing to answer: calling `approve()` on one you built by hand raises `RuntimeError`. That makes events easy to construct in tests of your own handlers: call the handler with one and check its return value.

```python
request = zc.ApprovalRequested("s", "c", "git status")
assert zc.approve_commands("git status")(request) is True
```

## Questions in detail

`QuestionAsked` carries:

| Field | Meaning |
| --- | --- |
| `question` | What was asked. |
| `options` | The choices it offered, possibly empty. The answer may still be free text. |
| `allow_multiple` | Whether more than one option may be chosen. |

The answer goes to the model exactly as given. For a multiple choice, join the choices yourself:

```python
def choose(question: zc.QuestionAsked) -> str | None:
    if question.options and question.allow_multiple:
        return ", ".join(question.options[:2])
    if question.options:
        return question.options[0]
    return None
```

An empty answer raises `ValueError` from `answer()`; call `decline()` to refuse. The questions a run asked are listed in `result.questions`.

If your program cannot answer questions at all, turn the tool off so the model never asks:

```python
async with zc.Client(".", ask_user_enabled=False) as client:
    ...
```

## Unattended checklist

For a job that runs with nobody watching:

1. Choose a permission level on purpose: `deny` if the model should only read and edit, `safe` if it may look around.
2. If it needs to run something, name it with `approve_commands`, not `approve_all`.
3. Set `ask_user_enabled=False`, or give an `on_question` that answers from your configuration.
4. Set a `timeout`. See [Errors & timeouts](./errors).
5. Keep the result's `tools` and `failed_tools` in your logs.
