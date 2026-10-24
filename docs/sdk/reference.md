---
title: API reference
---

# API reference

Every public name of the SDK, grouped by module. Signatures are those of the released package; the descriptions point to the page that explains the behaviour in context.

The package exports the everyday names from `zettcode.sdk`. Everything else is in a submodule, which is just as light to import.

| Module | Holds |
| --- | --- |
| [`zettcode.sdk`](#zettcode-sdk) | `Client`, `Session`, `RunStream`, `prompt`, `prompt_sync`, `RunResult`, `Usage`, `Image`, the common events and handlers, three errors |
| [`zettcode.sdk.client`](#zettcode-sdk-client) | `Client`, `Sessions`, `PluginReport`, `prompt`, `prompt_sync` |
| [`zettcode.sdk.session`](#zettcode-sdk-session) | `Session`, `RunStream` |
| [`zettcode.sdk.events`](#zettcode-sdk-events) | every event, `AnyEvent` |
| [`zettcode.sdk.types`](#zettcode-sdk-types) | the values methods return |
| [`zettcode.sdk.handlers`](#zettcode-sdk-handlers) | approval rules and handler types |
| [`zettcode.sdk.models`](#zettcode-sdk-models) | `list_models`, `add_model`, `update_model`, `remove_model` |
| [`zettcode.sdk.errors`](#zettcode-sdk-errors) | every error |

## zettcode.sdk

The names importable from the package itself:

```python
from zettcode.sdk import (
    Client,
    Session,
    RunStream,
    prompt,
    prompt_sync,
    RunResult,
    Usage,
    Image,
    TextDelta,
    ReasoningDelta,
    ToolStarted,
    ToolFinished,
    ServerToolStarted,
    ServerToolFinished,
    ApprovalRequested,
    QuestionAsked,
    Finished,
    approve_all,
    approve_commands,
    deny_all,
    add_model,
    list_models,
    update_model,
    remove_model,
    ZettCodeError,
    ConfigurationError,
    RunError,
)
```

They are loaded on first use, so importing the package costs next to nothing. `dir(zettcode.sdk)` lists them without loading anything.

## zettcode.sdk.client

### `prompt`

```python
async def prompt(
    text,
    /,
    *,
    workspace=None,
    config=None,
    config_path=None,
    models=None,
    model=None,
    effort=None,
    permission=None,
    resume=None,
    images=(),
    mentions=False,
    on_approval=None,
    on_question=None,
    on_event=None,
    timeout=None,
    **settings,
) -> RunResult: ...
```

Makes a client, runs one request, closes the client, and returns the result. Takes the arguments of `Client` and of `Client.run`. See [Running prompts](./running#one-shot-calls).

### `prompt_sync`

```python
def prompt_sync(text, /, **options) -> RunResult: ...
```

The blocking form of `prompt`, for code that is not async. Raises `RuntimeError` when called from inside a running event loop.

### `Client`

```python
class Client:
    def __init__(
        self,
        workspace=None,
        *,
        config=None,
        config_path=None,
        models=None,
        model=None,
        effort=None,
        permission=None,
        resume=None,
        **settings,
    ) -> None: ...
```

The agent for one workspace. An async context manager. See [Client & configuration](./client).

| Raises | When |
| --- | --- |
| `ConfigurationError` | The configuration, or a model, effort or permission chosen from it, is not usable. |
| `WorkspaceConflictError` | Another open client works in a different directory. |
| `SendError` | `send` could not reach anyone; `reason` says why. |
| `SessionNotFoundError` | `resume` names a session that cannot be read. |

#### Properties

| Property | Type | Meaning |
| --- | --- | --- |
| `workspace` | `Path` | The resolved workspace directory. |
| `config` | `ZettCodeConfig` | The configuration in force. |
| `closed` | `bool` | Whether `aclose()` has run. |
| `session` | `Session` | The current conversation. |
| `sessions` | `Sessions` | The stored conversations. |
| `models` | `tuple[ModelInfo, ...]` | The configured models; the active one is marked. |
| `model` | `ModelInfo` | The active model. |
| `effort` | `str` | The reasoning level the next run uses. |
| `efforts` | `tuple[str, ...]` | The levels the active model accepts. |
| `permission` | `str` | The shell permission level. |
| `permissions` | `tuple[str, ...]` | `("deny", "ask", "safe", "full")`. |
| `harness` | `bool` | Whether the just-in-time harness is on. |
| `usage` | `Usage` | What the current session has spent. |
| `plugins` | `PluginReport` | The plugins that loaded, and the failures. |
| `self_compaction` | `bool` | Whether the model may compact this session itself. |
| `self_compaction_choice` | `bool \| None` | This session's own choice, or `None` when it follows the configuration. |

#### Methods

| Method | Returns | Does |
| --- | --- | --- |
| `prompt(prompt, *, images, mentions, on_approval, on_question, on_event, timeout, raw, keep_events, defer_answers)` | `RunStream` | Sends a prompt on the current session. Await the result for a `RunResult`; iterate it for events. |
| `stream(...)` | `RunStream` | The same method as `prompt`. |
| `run(prompt, *, images, mentions, on_approval, on_question, on_event, timeout, keep_events)` | `RunResult` (awaitable) | `await client.prompt(...)` as a call. Has no `raw`. |
| `use_model(name)` | `ModelInfo` | Chooses the model; takes a name or a `ModelInfo`. |
| `use_effort(name)` | `str` | Chooses the reasoning level. |
| `use_compact_percent(percent)` | `tuple[ModelInfo, str \| None]` | Moves the compaction point (a share of the window, above 0 and at most 100) from the next request on, and rewrites the configuration file. The second value says why the file was not written, or is `None`. |
| `use_permission(name)` | `str` | Chooses the permission level; applies from the next shell command. |
| `mentions(query="", *, limit=50)` | `tuple[MentionInfo, ...]` | The `@` resources matching a query, for a completion menu. With `sessions_enabled=True`, the other running sessions come first, as they do in the terminal. |
| `await join_sessions(on_message)` | `bool` | Join the session broker, so other ZettCode sessions can find this one and send it messages. `on_message` is called with each `IncomingMessage` and returns a `Receipt`; `False` means sessions are switched off for this client. |
| `await send(to, text)` | `Delivered` | Sends a message to another session by handle or id, as the reader's own words; needs `join_sessions`. Raises `zettcode.sdk.errors.SendError` (its `reason` says why) when nobody could be reached. |
| `relay(message, *, on_approval, on_question, on_event, timeout, raw, keep_events, defer_answers)` | `RunStream` | Runs one turn for a message another session sent, framed with who it came from. |
| `await usage_ledger()` | `WorkspaceUsage` | What every stored session of the workspace spent, by session, model and day. |
| `await session_stats(ids=None)` | `tuple[SessionStatsInfo, ...]` | Stored totals of some sessions, or of the current one. |
| `use_self_compaction(choice)` | `bool` | Let the model compact this session itself (`True`), stop it (`False`), or follow the default (`None`). |
| `await check_models(*, timeout=30)` | `tuple[ModelCheck, ...]` | Ask every configured model one short question, as `zettcode doctor`. |
| `aclose()` | — | Stops a run in progress, leaves the broker and releases everything. Safe to call twice. |

`use_model`, `use_effort` and `use_permission` raise `ConfigurationError` for a choice that does not exist, with the valid ones in the message.

### `Sessions`

`client.sessions`.

| Method | Returns | Does |
| --- | --- | --- |
| `await list(*, limit=20)` | `list[SessionInfo]` | Stored sessions, most recently active first. |
| `new()` | `Session` | Starts an empty conversation and makes it current. |
| `await open(session_id)` | `Session` | Continues a stored conversation and makes it current. |
| `await latest()` | `Session \| None` | Continues the most recently active one. |

### `PluginReport`

Frozen dataclass: `loaded: tuple[str, ...]`, `failures: tuple[str, ...]`.

## zettcode.sdk.models

The configuration file's models, for setting up a machine before there is a client. See [Models before there is a client](./client#models-before-there-is-a-client).

```python
def list_models(path=None) -> tuple[ModelInfo, ...]: ...
def add_model(entry, *, path=None) -> tuple[ModelInfo, ...]: ...
def update_model(name, changes, *, path=None) -> tuple[ModelInfo, ...]: ...
def remove_model(name, *, path=None) -> tuple[ModelInfo, ...]: ...
```

`entry` and `changes` are the file's keys (`model`, `token`, `display_model`, `base_url`, `anthropic`, `responses_api`, `chat`, `multimodal`, `temperature`, `context_window`, `compact_percent`, `reasoning_efforts`). `path` defaults to `$ZETTCODE_CONFIG` or `~/.zettcode/config.toml`. Every call returns the whole list, with no model marked active, and refuses a file it cannot read back; the last model cannot be removed. In `changes`, a key whose value is `None` is removed from the entry: `{"temperature": None}` goes back to the provider's own, and `{"anthropic": None, "chat": True}` moves a model to chat completions without leaving `anthropic = false` behind.

## zettcode.sdk.session

### `Session`

A handle on one stored conversation. Obtain it from `client.session`, `client.sessions`, or `Session.fork()`.

#### Properties

| Property | Type | Meaning |
| --- | --- | --- |
| `id` | `str` | The session's identity. |
| `title` | `str \| None` | Its name, or `None` until it has one. |
| `usage` | `Usage` | What this session has spent in total. |
| `locked` | `bool` | Whether another process has it open. |
| `path` | `Path` | The file the conversation is stored in. |
| `current` | `bool` | Whether the next run would use it without switching. |

#### Running

| Method | Returns |
| --- | --- |
| `prompt(prompt, *, images, mentions, on_approval, on_question, on_event, timeout, raw, keep_events, defer_answers)` | `RunStream` |
| `stream(...)` | `RunStream` (same method) |
| `await run(prompt, *, images, mentions, on_approval, on_question, on_event, timeout, keep_events)` | `RunResult` |
| `await ask(question, *, on_event=None, timeout=None)` | `str` |
| `ask_stream(question, *, on_event=None, timeout=None)` | `RunStream` |
| `steer(message)` | `bool` |
| `await resumable()` | `ResumeInfo \| None` |
| `resume_stream(*, on_approval, on_question, on_event, timeout, raw, keep_events, defer_answers)` | `RunStream` |
| `await resume(*, on_approval, on_question, on_event, timeout)` | `RunResult` |

`prompt` raises, at the call: `ValueError` (empty prompt, bad `timeout`), `TypeError` (a piece that is not text or `Image`), `ConfigurationError` (images for a model that cannot read them), `SessionBusyError`, `ClientClosedError`. Awaiting or iterating the run raises `RunError`, `RunTimeoutError`, `SessionLockedError` and whatever a handler raises.

#### Working on the conversation

| Method | Returns | Raises |
| --- | --- | --- |
| `await history()` | `list[Message]` | `SessionNotFoundError` |
| `await rename(title)` | `str` | `ValueError`, `SessionLockedError`, `SessionBusyError` |
| `await name_it()` | `str \| None` | — |
| `await fork()` | `Session` | `SessionNotFoundError`, `SessionBusyError` |
| `await export(path=None)` | `Path` | `ValueError` when nothing is stored |
| `await context()` | `ContextReport \| None` | — |
| `await compact()` | `Compaction \| None` | `NothingToDoError`, `SessionLockedError`, `SessionBusyError` |

See [Sessions](./sessions).

### `RunStream`

One run. Returned by `prompt`, `stream` and `resume_stream`.

| Member | Meaning |
| --- | --- |
| `await run` | Takes the rest of the events and returns the `RunResult`. |
| `async for event in run` | Yields the events as they happen. |
| `async with run` | Closes the run on leaving the block. |
| `await run.aclose()` | Stops the run and frees the client. Safe to call twice. |
| `run.result` | The `RunResult`, or `None` until the run has ended on its own. |

## zettcode.sdk.events

Every event is a frozen dataclass deriving from `Event(session_id: str)`.

| Class | Fields beyond `session_id` |
| --- | --- |
| `TextDelta` | `text` |
| `ReasoningDelta` | `text` |
| `ReasoningStarted` | — |
| `ReasoningFinished` | — |
| `ToolStarted` | `call_id`, `name`, `arguments` |
| `ToolFinished` | `call_id`, `name`, `output`, `ok`, `skipped=False` |
| `ServerToolStarted` | `call_id`, `name`, `arguments` — a tool the endpoint runs, such as a web search |
| `ServerToolFinished` | `call_id`, `name`, `arguments`, `output`, `ok` — the query, the pages, and whether it worked |
| `ApprovalRequested` | `call_id`, `command`, `timeout_seconds=None`, `remember_supported=False` |
| `QuestionAsked` | `call_id`, `question`, `options=()`, `allow_multiple=False` |
| `UsageUpdated` | `usage` |
| `CompactionStarted` | — |
| `CompactionDelta` | `text` |
| `CompactionFinished` | `applied`, `compaction=None` |
| `ModelStopped` | `reason`, `message=None` |
| `Steered` | `text` |
| `SteeringFinished` | — |
| `SteeringInterrupted` | `text` |
| `Notice` | `text`, `level` |
| `Finished` | `text` |
| `RawEvent` | `event` |

`AnyEvent` is the union of all of them.

### `ApprovalRequested`

| Member | Meaning |
| --- | --- |
| `approve(*, remember=False)` | Let the command run. `remember` applies only if `remember_supported`. |
| `deny()` | Refuse it. |
| `answered` | Whether it was settled, by you or the run's handler. |
| `approved` | `True`, `False`, or `None` while unanswered. |

### `QuestionAsked`

| Member | Meaning |
| --- | --- |
| `answer(text)` | Answer it. Raises `ValueError` for an empty answer. |
| `decline()` | Tell the model it was cancelled. |
| `answered` | Whether it was answered or declined. |

The first answer wins. Repeating it is harmless; the opposite raises `ValueError`. See [Approvals & questions](./approvals#answering-twice).

## zettcode.sdk.types

All are frozen dataclasses with `__slots__`.

### `Usage`

`input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_write_tokens`, `reasoning_tokens` (all `int`, default `0`), `seconds: float`, `requests: int`, `context_tokens: int`.

| Member | Meaning |
| --- | --- |
| `total_tokens` | Input plus output. |
| `cache_hit_rate` | Cached share of the input, or `None`. |
| `output_rate` | Tokens per second of model time, or `None`. |
| `since(earlier)` | What was spent after `earlier`; counters never below zero. |

### `RunResult`

| Field | Type |
| --- | --- |
| `text` | `str` |
| `session_id` | `str` |
| `usage` | `Usage` |
| `tools` | `tuple[ToolRecord, ...]` |
| `stop` | `str \| None` |
| `stop_message` | `str \| None` |
| `questions` | `tuple[str, ...]` |
| `events` | `tuple[Event, ...]` |

Properties: `ok` (`stop is None`) and `failed_tools`.

### `ToolRecord`

`id`, `name`, `arguments: dict`, `output: str`, `ok: bool`, `skipped: bool = False`.

### `Image`

`Image(data: bytes, media_type: str)` and `Image.from_path(path)`. Media types: `image/png`, `image/jpeg`, `image/gif`, `image/webp`. Raises `ValueError` for empty data or another type.

### `ModelInfo`

`name`, `model`, `context_window: int`, `multimodal: bool`, `efforts: tuple[str, ...]`, `active: bool = False`.

### `SessionInfo`

`id`, `title: str or None`, `created_at: datetime`, `updated_at: datetime`.

### `Message` and `ToolCallInfo`

`Message(role, text, tool_calls=(), tool_call_id=None, tool_name=None, ok=True, images=0)`.
`ToolCallInfo(id, name, arguments)`.

### `MentionInfo`

`token`, `kind`, `name`, `description`.

### `IncomingMessage`

`sender_id`, `sender`, `text`, `via`, `hops`. A message another ZettCode session sent: what `join_sessions` hands its callback, and what `relay` answers. `via` is `"user"` when the sender's reader typed it, `"agent"` when its agent did, `"external"` for a program that is not a ZettCode session.

### `Receipt`, `Delivered`

`Receipt(accepted, reason="", disposition="")` is what the `join_sessions` callback returns to the sender: whether the message was taken, why not, and whether its turn `"started"` or is `"queued"`. `Delivered(to, disposition)` is what `send` returns: the handle of the session that took the message and the same disposition.

### `Totals`

What a tally in the usage ledger holds: `requests`, `input_tokens`, `output_tokens`, `cache_read_tokens`, `reasoning_tokens` (all `int`), with `total_tokens` and `cache_share` (`None` with no input) worked out.

### `SessionTotals`, `ModelTotals`, `DayTotals`, `WorkspaceUsage`

`SessionTotals(id, title, started, updated, tokens, models, entries)`; `ModelTotals(model, tokens)`; `DayTotals(day, tokens)`. `WorkspaceUsage(sessions, models, days, total)` is what `usage_ledger()` returns: sessions most recently active first, models busiest first, days oldest first.

### `SessionStatsInfo`

`id`, `entries`, `requests`, `input_tokens`, `output_tokens`, `cache_read_tokens`, `reasoning_tokens`, with `total_tokens` and `cache_share` worked out. One row of the terminal's `/resume` panel.

### `ModelCheck`

`model`, `model_id`, `ok`, `seconds`, `detail`, `input_tokens: int | None`, `output_tokens: int | None`. One model's answer to `check_models()`.

### `ContextReport` and `ContextShare`

`ContextReport(window, used, measured_by, shares=(), partial=False, from_provider=False)` with properties `free` and `fraction`, and `measured` (what the tokenizer counted, which `shares` add up to; `used` may be the provider's own count), `estimated` (the shares are a characters-per-token guess) and the methods `percent(tokens)` (a share of the window) and `share(tokens)` (a share of `measured`, which is where the context goes). `ContextShare(name, tokens, items=0)`.

### `Compaction` and `ResumeInfo`

`Compaction(summary, compressed, kept)`. `ResumeInfo(kind, description)`.

## zettcode.sdk.handlers

| Name | Meaning |
| --- | --- |
| `approve_all(request)` | Approves everything. |
| `deny_all(request)` | Denies everything. |
| `approve_commands(*commands)` | Returns a handler that approves the named commands and denies the rest. Raises `ValueError` for a blank rule or one containing a shell character. |
| `ApprovalHandler` | `Callable[[ApprovalRequested], bool \| None \| Awaitable[bool \| None]]` |
| `QuestionHandler` | `Callable[[QuestionAsked], str \| None \| Awaitable[str \| None]]` |
| `SHELL_META` | The characters that stop a command from matching a prefix rule. |

## zettcode.sdk.errors

See [Errors & timeouts](./errors) for the hierarchy and when each is raised.

| Class | Bases | Extra attributes |
| --- | --- | --- |
| `ZettCodeError` | `Exception` | — |
| `ConfigurationError` | `ZettCodeError`, `ValueError` | — |
| `ClientClosedError` | `ZettCodeError` | — |
| `SessionBusyError` | `ZettCodeError` | — |
| `SessionLockedError` | `ZettCodeError` | — |
| `SessionNotFoundError` | `ZettCodeError`, `LookupError` | — |
| `NothingToDoError` | `ZettCodeError` | — |
| `WorkspaceConflictError` | `ZettCodeError` | — |
| `SendError` | `ZettCodeError` | `reason` |
| `RunError` | `ZettCodeError` | `retryable`, `partial_text` |
| `RunTimeoutError` | `RunError`, `TimeoutError` | `seconds` |

## Types you may want in annotations

```python
from zettcode.sdk import Client, Session, RunStream, RunResult
from zettcode.sdk.events import AnyEvent
from zettcode.sdk.handlers import ApprovalHandler, QuestionHandler
from zettcode.sdk.types import ModelInfo, SessionInfo, Message, ContextReport
```

The package ships a `py.typed` marker, so type checkers read the annotations.
