---
title: Running prompts
---

# Running prompts

This page covers sending a prompt and getting something back: the three ways to call, every argument, what the result holds, and the variations — images, `@` references, side questions, steering, and one-shot calls.

## Three ways to call

All of them send a prompt on the current session of a client. They differ in what you get back.

```python
import zettcode.sdk as zc

async with zc.Client(".", permission="safe") as client:
    # 1. Wait for the end and get the result.
    result = await client.prompt("explain this module")

    # 2. Watch it happen.
    async with client.prompt("explain this module") as run:
        async for event in run:
            ...
    result = run.result

    # 3. The same as 1, spelled as a call.
    result = await client.run("explain this module")
```

`client.prompt(...)` returns a `RunStream` immediately, without sending anything. The request starts when you first await or iterate it. That is why the same call can be used both ways.

`client.stream(...)` is the same method as `prompt` under a name that says what you intend. Use whichever reads better; they cannot differ.

The same three exist on a `Session` (`session.prompt`, `session.stream`, `session.run`), and the module-level `zc.prompt()` does a whole lifecycle for one request.

## Arguments

`Client.prompt`, `Session.prompt` and `Session.run` take the same arguments.

| Argument | Default | Meaning |
| --- | --- | --- |
| `prompt` | required | Text, or a list of text and `Image` pieces in reading order. |
| `images` | `()` | Images to put after the prompt. |
| `mentions` | `False` | Resolve `@skill` and `@path` references as the terminal does. |
| `on_approval` | `None` | Decides each shell command that needs approval. See [Approvals & questions](./approvals). |
| `on_question` | `None` | Answers each question the model asks. |
| `on_event` | `None` | Called with every event, as it happens. A function or a coroutine function. |
| `timeout` | `None` | Seconds to allow the whole run. |
| `raw` | `False` | Also yield the underlying `zett-agent` event as a `RawEvent`. (`prompt` and `stream` only.) |
| `keep_events` | `False` | Keep every event in `result.events`. |

A prompt that is empty, a `timeout` that is not a positive number, or a list holding something other than text and images raises `ValueError` or `TypeError` **at the call**, before anything is sent.

```python
try:
    client.prompt("   ")
except ValueError as error:
    print(error)       # The prompt is empty
```

## The result

```python
result = await client.prompt("run the tests and fix what fails", on_approval=zc.approve_commands("pytest"))
```

| Attribute | Meaning |
| --- | --- |
| `result.text` | The model's final answer. If it ended without one, what was streamed. |
| `result.session_id` | The session the run belongs to. Pass it as `resume=` later. |
| `result.usage` | A `Usage` for this run alone. |
| `result.tools` | A tuple of `ToolRecord`: every call, in order. |
| `result.failed_tools` | The records that did not succeed. |
| `result.stop` | `None` when the model finished, else why it did not. |
| `result.stop_message` | The provider's sentence about a stop, when it gave one. |
| `result.ok` | `True` exactly when `stop` is `None`. |
| `result.questions` | The questions the model asked, in order. |
| `result.events` | Every event, when `keep_events=True`; otherwise empty. |

### Reading the tool calls

```python
for tool in result.tools:
    status = "ok" if tool.ok else "skipped" if tool.skipped else "failed"
    print(f"{tool.name:<12} {status:<8} {tool.arguments}")

if result.failed_tools:
    print("Some tools failed:", [tool.name for tool in result.failed_tools])
```

A `ToolRecord` carries `id`, `name`, `arguments`, `output` (what the tool returned, or the failure text), `ok` and `skipped`.

### A run that did not simply finish

A refusal or a cut-off is a *result* with a `stop`, not an exception. The model answered; it just did not finish the way you hoped.

```python
result = await client.prompt("...")
if not result.ok:
    match result.stop:
        case "refusal":
            print("The model declined:", result.stop_message)
        case "max_output":
            result = await client.prompt("continue")
        case "context_full":
            await client.session.compact()
```

The values are `refusal`, `max_output`, `context_full`, `paused`, `interrupted` and `other`. Errors from the provider or the network are different: they raise `RunError`. See [Errors & timeouts](./errors).

### Usage

`result.usage` is what *this run* spent. `client.usage` and `session.usage` are the session's total.

```python
before = client.usage
result = await client.prompt("...")

print(result.usage.total_tokens)         # this run
print(client.usage.total_tokens)         # the session so far
print(f"{result.usage.cache_hit_rate:.0%} of the input came from cache")
print(f"{result.usage.output_rate:.0f} tokens/s")
```

| `Usage` field | Meaning |
| --- | --- |
| `input_tokens` | Everything sent to the model, **including** cache reads and writes. |
| `output_tokens` | Everything generated, **including** reasoning. |
| `cache_read_tokens`, `cache_write_tokens` | The cache parts of the input. |
| `reasoning_tokens` | The reasoning part of the output. |
| `seconds` | Wall time spent inside model calls. |
| `requests` | How many model calls were made. |
| `context_tokens` | How full the context was on the newest call. |
| `total_tokens` | `input_tokens + output_tokens`; nothing is counted twice. |
| `cache_hit_rate` | The cached share of the input, or `None` before any input. |
| `output_rate` | Tokens per second of model time, or `None`. |

`usage.since(earlier)` subtracts two readings, never going below zero.

## Images

A prompt can mix text and images, in the order they should be read. The model must be `multimodal`.

```python
png = zc.Image.from_path("screenshot.png")

result = await client.prompt(["What is wrong with this layout? ", png])
result = await client.prompt("Compare these", images=[zc.Image.from_path("a.png"), zc.Image.from_path("b.webp")])
```

`Image(data, media_type)` takes encoded bytes, and the type must be `image/png`, `image/jpeg`, `image/gif` or `image/webp`. `Image.from_path` takes the type from the extension. A bad image raises `ValueError` when it is made. An image sent to a model that cannot read images raises `ConfigurationError` before anything is sent, and the message says which model.

Images are in the stored conversation as a count (`Message.images`); the bytes are not kept in history.

## Mentions

The terminal's composer resolves `@skill` and `@path` references. In the SDK they are left as plain text by default, since `@` is also in email addresses and decorators. Turn them on when you want the terminal's behaviour:

```python
result = await client.prompt("Use @code-review on @src/parser.py", mentions=True)
```

The references are resolved the way the terminal resolves them, and instructions for what they point at are added behind the prompt. The stored history keeps what you typed (`Message.text` of a user message is the text you sent, not those added instructions).

## Side questions

`session.ask()` puts a question to the model with the whole conversation in view and adds nothing to it — neither the question nor the answer joins the history the next run is built from. The footing is read-only.

```python
await client.prompt("refactor the parser")
answer = await client.session.ask("which functions did you touch?")
print(answer)

await client.prompt("now add tests")        # the model never saw the side question
```

It returns the answer text and raises `ValueError` for an empty question. Like any run, it needs the client to be free.

## Steering a run

Send a message to a request that is in progress. The agent drops what it was doing and takes the message into account at the next boundary.

```python
async with client.prompt("investigate the failing test") as run:
    steered = False
    async for event in run:
        if isinstance(event, zc.ToolStarted) and event.name == "bash" and not steered:
            steered = client.session.steer("don't run commands; read the code instead")
```

`steer` returns `True` when a running request accepted the message and `False` when nothing was running, the client was closed, or the message was blank. Nothing is queued for later. The `Steered` event in the stream confirms the request took it.

`steer` is an ordinary method, not a coroutine, so it can be called from inside the event loop above, from a callback, or from another task that holds the client.

## Stopping early

Leave the loop and the run is closed, provided you used `async with`.

```python
async with client.prompt("write a long essay") as run:
    async for event in run:
        if isinstance(event, zc.TextDelta):
            print(event.text, end="")
            if "TODO" in event.text:
                break                    # the run is closed on leaving the block
```

After a break, the client is free for the next prompt. What the run had already added to the conversation stays.

::: warning
The prompt of a run you stopped stays in the conversation, answered or not. The model sees it again on the next request and may answer it as well: after cancelling "write forty tips" and sending "say alive", the reply to the second can carry on with the tips. If that is not wanted, start a [new session](./sessions#finding-sessions) for the next prompt, or tell the model that the earlier request is dropped.
:::

Without `async with`, call `await run.aclose()`. A run that is neither finished nor closed keeps the client busy until it is garbage collected.

## Combining iteration and awaiting

You can iterate part of a run and then await the rest:

```python
async with client.prompt("explain the design") as run:
    async for event in run:
        if isinstance(event, zc.ToolStarted):
            break                         # I have seen enough to know it is working
    result = await run                    # take the remainder
```

Awaiting a run that has already finished and been read is an error rather than a hang. Iterating a finished run ends immediately.

## Callbacks instead of a loop

`on_event` is for observing without owning the loop, such as logging or updating a progress display. It sees every event, including the ones a handler answers.

```python
events = []

async def record(event):
    events.append(event)
    await send_to_dashboard(event)

result = await client.prompt("...", on_event=record)
```

If the callback raises, the run is stopped and the error reaches your `await` unchanged.

## One-shot calls

`zc.prompt()` makes a client, runs one request, and closes everything:

```python
result = await zc.prompt(
    "list the public functions in src/parser.py",
    workspace=".",
    permission="deny",
    timeout=60,
)
```

It takes the arguments of `Client` and of `run`. For more than one prompt, keep a `Client`, so the conversation carries on and the setup cost is paid once.

### From synchronous code

```python
result = zc.prompt_sync("check the parser", workspace=".", permission="safe")
print(result.text)
```

`prompt_sync` runs the event loop itself. It refuses to run inside an already-running loop (a notebook, an async framework) and raises `RuntimeError`; use `await zc.prompt(...)` there.

## Raw events

For what the SDK does not model, start the run with `raw=True` to also receive the underlying `zett-agent` event, as a `RawEvent` just before the typed events it produced.

```python
from zettcode.sdk.events import RawEvent

async with client.prompt("...", raw=True) as run:
    async for event in run:
        if isinstance(event, RawEvent):
            print(event.event.type)
```

`RawEvent` and `AnyEvent` live in `zettcode.sdk.events`.
