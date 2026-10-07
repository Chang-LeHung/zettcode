# Models and context

ZettCode talks to any OpenAI-compatible endpoint: a hosted API, a gateway in
front of several providers, or a model running on your own machine. What it
needs to know is in [Configuration](/guide/config#models).

## Switching

`/model` opens a picker over the conversation. `Enter` selects for **later**
requests — the one already running is not disturbed — and the header shows the
new name immediately. `/model DeepSeek Pro` also works, matching either the display
name or the model id, for when you know exactly what you want.

Each model keeps its own token, endpoint, and window, so switching between a
local server and a hosted one is one keystroke rather than an edit and a
restart.

For example, configure `DeepSeek Pro` and `DeepSeek Flash` with the
[two-model example](/guide/config#configuring-more-than-one-model), then try:

```text
/model DeepSeek Pro
Explain the trade-offs in this module before making changes.
/model DeepSeek Flash
Read this screenshot and describe the error message.
```

The screenshot request needs an attached image and a model configured with
`multimodal = true`. Choosing a model does not attach an image for you. The
conversation remains the same when you switch; use `/new` for a clean start.

## Reasoning effort

`/effort` picks how much the model should think before answering:

| Level | What it is for |
| --- | --- |
| `off` | Request no deliberate reasoning, subject to the endpoint's support. |
| `minimal` | A token of thought, fastest. |
| `low` | Quick answers for small edits. |
| `medium` | The default balance. |
| `high` | More thought on hard problems. |
| `xhigh` | A long think on hard problems. |
| `max` | The highest budget the provider accepts. |
| `ultra` | Highest requested level; availability depends on the endpoint. |

The choice applies to later requests for the current application run, and the
header shows which one is selected. It is not a saved setting in `config.toml`.
For example:

```text
/effort low
Explain what this regular expression matches.
/effort high
Review this locking code for deadlocks and races; do not edit it yet.
```

The endpoint decides the actual reasoning budget. Not all endpoints support
all levels, and a gateway may reject an unsupported value rather than map it.
DeepSeek documents its current mapping in
[Thinking Mode](https://api-docs.deepseek.com/guides/thinking_mode).
In this client, Chat Completions with `/effort off` omits `reasoning_effort`;
it does not send DeepSeek's separate `thinking` toggle, so it is not a guarantee
that a provider with thinking enabled by default will disable it.

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

Do not confuse the two percentages:

| Display | Calculation | Example |
| --- | --- | --- |
| Status `ctx` | Context tokens ÷ configured window | 100,000 of 1,000,000 tokens is `ctx 10.0%`. |
| A `/context` row | That source's tokens ÷ all current context tokens | 60,000 tool-output tokens out of 100,000 total is `60.0%`. |

The category shares add to 100% before display rounding. `Count` is the number
of messages, tool definitions, or instruction items in that category, not the
number of conversation turns. A resumed session can show a breakdown too.
Before tools/environment notes have been assembled in the current process,
the footer can say `notes and tools pending`; treat that snapshot as partial.

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

Try this after several turns or a large file read:

```text
/context
/compact
/context
```

Close each context panel with `Esc` before typing the next command. `/compact`
starts the summary immediately and shows an animated `Compacting` row. Compare
the second report with the first: older details are replaced by a summary,
while the recent working context remains. This is not `/clear`: it changes
what later model requests carry, not just what is visible on screen.

If the most recent checkpoint already covers the conversation, another manual
compaction is refused with a notice. Continue the conversation before trying
again. A summary may lose detail; ask the model to re-read a specific file when
exact text matters.

## Reading the numbers

`↑18.4k ↓900 · 71.2% cached · 74 tok/s · ctx 12.3%` — in order: tokens sent,
tokens generated, the share of the input the provider served from its cache,
generated tokens per second of model time, and how full the window was on the
newest request. Input/output totals accumulate across the session; context
occupancy is a snapshot, not an accumulated percentage.

| Field | How to read it |
| --- | --- |
| `↑` / `↓` | Cumulative input and output tokens reported by the provider. Repeated context counts as input each time it is sent. |
| `cached` | Cumulative cache-hit input tokens ÷ cumulative input tokens. 60,000 hits out of 100,000 input tokens is `60.0%`. |
| `tok/s` | Output tokens divided by measured model time; not wall time spent on tools, approvals, or reading the answer. |
| `ctx` | Latest context occupancy relative to the selected model's configured window. |

An endpoint that does not report cache-hit usage cannot provide a meaningful
hit-rate measurement here. These statistics are not a bill; check the
provider's dashboard for charged usage.

The cache figure is worth understanding, because it is where time and money go.
Providers cache a *prefix* of the request: if the beginning of a request is
byte-for-byte identical to the previous one, that part is billed and served more
cheaply. That is why the system prompt carries the date and not the time,
project instructions are read in a fixed order, and `/context` is safe to open
between turns — a stable prefix helps reuse cached input. There is no universal
"good" percentage: model switches, compaction, changing tool definitions, and
the provider's cache lifetime can all lower it. Newly generated output can only
become cached input when a later request sends it back.
