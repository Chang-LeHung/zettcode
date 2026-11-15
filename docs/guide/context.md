# The context window

Every model has a limit on how much it can read at once: its **context window**. Everything in one request competes
for it — the instructions, the tool schemas, the messages, and the output of every tool call.

`/context` shows the newest request: how full the window is, how close it is to compaction, and where its tokens came
from. The status line's `ctx` figure is the same measurement, in short.

```text
/context
```

The page describes the **last request the model received**, not the transcript on your screen: a typed but unsent
message is not in it, and a tool result only once sent back. `Esc` closes it, and opening it mid-request is safe.
`No request yet` means this session has not sent one.

## Reading the picture

![The /context page: a gauge of the window, three numbers, and the sources of the request](/screens/context.svg)

The two lines under the title say which session this picture belongs to. `Workspace` is the directory the session
works in, and the one both the tools that read or write a file and the shell start from; `Session` is the file the
conversation is stored in. On macOS and Linux a path inside your home directory starts with `~`; either way, a path
too long for the terminal keeps its end, which names the project or the file.

### The window

```text
Window   103,241 / 200,000 tokens   51.6% full
```

The first number is what the request carried; the second is the model's configured window (`context_window` in
[`config.toml`](/guide/config#models)); the third divides them.

The bar is that figure drawn to scale, and its **colour is about danger, not size**: green well below the compaction
point, amber from three quarters of the way there, red at it. At a mark of 80%, amber begins at 60% of the window.

```text
                      compacts at 160,000 tokens (80.0%) ▲
```

The `▲` marks where ZettCode compacts instead of sending more: `compact_percent` of the window, 80% here, so 160,000
of 200,000. Reaching it does not mean the window is full — the older conversation is summarized before the next
request goes out.

Later in the same turn:

![The same page near the trigger: an amber gauge and a compaction summary](/screens/context-near.svg)

Three lines divide the same budget:

| Line | What it is |
| --- | --- |
| `Used` | Tokens in this request: the first number on the `Window` line. |
| `Until compaction` | What can be added before the request is summarized. The real headroom. |
| `Free in window` | What is left before the model refuses the request at all. |

### Where the tokens went

```text
Where it goes   how the 103,241 tokens divide between sources
████████████████████████████████████████████████████████████████████████
```

One bar divides the request; each segment has a row underneath on its own scale, so a small source is still visible.

| Source | What it holds |
| --- | --- |
| `System prompt` | ZettCode's instructions: the tools, the working directory, the date. Stable, so the provider can cache it. |
| `Environment notes` | Project instructions such as `AGENTS.md`, and the notes added at session start. |
| `Tool schemas` | Every tool offered — name, description, argument schema. Nine tools means nine, used or not. |
| `User messages` | What you typed, including `/btw`. An image costs a fixed count, not its file size. |
| `Assistant messages` | The model's answers, its reasoning when returned, and its tool calls. |
| `Tool output` | File contents, command output, search results. Usually the largest row. |
| `Compaction summary` | What an earlier compaction left in place of the older conversation. |

`Items` counts what `Tokens` was added up from: messages, tool definitions, summaries. It is not a count of turns.

`Share` is each source's part of what was counted, so the rows add up to 100%. `Tool output 60.1%` and `62,069` tokens
are not 60.1% of the window; they are 60.1% of the counted request. The window's own percentage is on the `Window`
line and nowhere else.

### Whose number it is

The footnote is the rule for reading every row:

```text
Total from the provider, which counts what it bills. Each source gets its share of that total,
worked out from a local count.
```

- The **total** is the provider's count of the request it received, which is what it bills.
- The **split** is ZettCode's, from a local count, because no provider reports a breakdown.
- So each row is that source's *share of the provider's total*: the number in its bar is a proportion, not a
  measurement.

A local count is right about what is bigger than what, not about absolute size: it uses one tokenizer, and the model
may use another.

![A session just reopened: two rows still pending](/screens/context-resumed.svg)

`Counted here; the provider has not reported this request yet` means the session was resumed and nothing has been sent
from it in this process. `Tool schemas` and `Environment notes` are built when a request is assembled, so those rows
read `pending` and the total is a lower bound. Send one message and run `/context` again.

## Moving the compaction point {#moving-the-mark}

The `Compress at` row above the keys is a rail with a knob: where the window is compacted, as a share of it. ← and →
move the knob by five percent, and a click sends it there. The `▲` under the gauge, the number and the
`Until compaction` line travel with it, so you see the effect before you decide. With reduced motion the knob does not
animate.

Nothing is written until `Enter`, which writes `compact_percent` into this model's entry in `config.toml` for the next
request. `Esc` leaves it as it was. If the file cannot be edited the change holds for this run, and the line says so.

## Compaction

When the next request would cross the trigger, the older conversation becomes one summary and the newest quarter of
the trigger stays verbatim, so the model keeps the immediate context. `/compact` does it now instead of waiting.

A summary is stored as its own record, not as a delete: that is why the transcript still ends with
`Conversation checkpoint`, and why a session compacted yesterday still resumes.

::: tip What compaction costs
Summarizing is one model call, so it takes a few seconds and shows `Compacting`. Do it early rather than at the moment
you need the space. If a summary would not be smaller than the text it replaces, ZettCode keeps the original.
:::

If the newest checkpoint covers the conversation, another manual compaction is refused. A summary may lose detail;
ask the model to re-read a file when exact text matters. The model can compact on its own if you allow it:
[self-compaction](/guide/commands#self-compaction).

## Keeping the request small

- **Read what you need.** A range of lines beats a whole file. Output is paid for on every request until it is
  compacted.
- **Turn off tools you do not use.** Every MCP server and every skill in scope adds schemas; see
  [Skills and MCP](/guide/skills-and-mcp).
- **Keep the stable part stable.** The system prompt and tool list are what the provider caches, so an unchanged
  prefix is cheaper. That is the `cached` figure on the status line and in `/usage`.

A large row names its own fix: `Tool output` means narrower reads, `Tool schemas` means fewer servers and skills,
`Environment notes` means shorter instructions.

## Next steps

- [Commands](/guide/commands): `/compact`, `/new`, and self-compaction.
- [Token usage](/guide/usage): what this project has spent.
- [The status line](/guide/models#reading-the-status-line): `ctx` and `cached` while a reply arrives.
