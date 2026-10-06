# Models and context

ZettCode talks to any OpenAI-compatible endpoint: a hosted API, a gateway in
front of several providers, or a model running on your own machine. What it
needs to know is in [Configuration](/guide/config#models).

## Switching

`/model` opens a picker over the conversation. `Enter` selects for **later**
requests — the one already running is not disturbed — and the header shows the
new name immediately. `/model GPT-4o` also works, matching either the display
name or the model id, for when you know exactly what you want.

Each model keeps its own token, endpoint, and window, so switching between a
local server and a hosted one is one keystroke rather than an edit and a
restart.

## Reasoning effort

`/effort` picks how much the model should think before answering:

| Level | What it is for |
| --- | --- |
| `off` | No deliberate reasoning; straight to the answer. |
| `minimal` | A token of thought, fastest. |
| `low` | Quick answers for small edits. |
| `medium` | The default balance. |
| `high` | More thought on hard problems. |
| `xhigh` | A long think on hard problems. |
| `max` | The highest budget the provider accepts. |
| `ultra` | Above `max`; a provider that cannot go that far maps it down. |

The level is per run, not per session: it applies to the next request and the
header always shows which one is in force. A provider that cannot express a
level maps it onto its closest supported value, so the deepest levels degrade
rather than fail.

## The context window

Every model has a limit. ZettCode tracks how full it is — `ctx 34.0%` in the
status line, and the full breakdown under `/context` — and compacts before it
overflows, using `compact_percent` from the model's configuration.

```
Context  103,241 / 128,000 tokens
  Source              Share    Count
  System prompt        1.9%      (1)
  Environment notes    4.8%      (2)
  Tool schemas        10.9%      (9)
  User messages        0.1%      (3)
  Assistant messages  22.2%     (12)
  Tool output         60.1%     (17)
~4 chars/token · esc back
```

The title compares the total against the model's window; the percentages are
shares of the context in use, so they add up to 100%. If a row is surprisingly
large, that is the thing to look at: a tool schema you never use, or a long file
that came back from a read. The footer names the counter that produced the
numbers — `tiktoken` when its encoding could be loaded, a
four-characters-per-token estimate otherwise.

## Compaction

When the newest request would cross the trigger, the conversation is summarized
before it is sent: the older part becomes one summary message, and the newest
quarter of the trigger stays verbatim, so the model keeps the immediate
context and loses only what was already said. `/compact` does it immediately.

A summary is stored as its own kind of record, not as a delete. That is why the
transcript still ends with `Conversation checkpoint`, why the models panel keeps
working, and why a session compacted yesterday still resumes correctly. Asking
by hand keeps only the last turn verbatim, where the automatic pass leaves a
quarter of the trigger behind.

::: tip What compaction costs
Summarizing is one model call, so it takes a few seconds — the transcript shows
`Compacting` while it runs. It is worth doing early rather than late: the
alternative is an endpoint error at the moment you are in the middle of
something. If a summary would not be smaller than the text it replaces,
ZettCode says so and keeps the original.
:::

## Reading the numbers

`↑18.4k ↓900 · 71.2% cached · 74 tok/s · ctx 12.3%` — in order: tokens sent,
tokens generated, the share of the input the provider served from its cache,
generated tokens per second of model time, and how full the window was on the
newest request. All of them are the provider's own numbers, accumulated over the
session.

The cache figure is worth understanding, because it is where time and money go.
Providers cache a *prefix* of the request: if the beginning of a request is
byte-for-byte identical to the previous one, that part is billed and served more
cheaply. That is why the system prompt carries the date and not the time,
project instructions are read in a fixed order, and `/context` is safe to open
between turns — a stable prefix is what keeps the hit rate high.
