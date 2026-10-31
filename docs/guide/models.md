# Models and context

ZettCode talks to any OpenAI-compatible endpoint: a hosted API, a gateway in
front of several providers, or a model running on your own machine. An entry can
ask for Anthropic's Messages API instead with `anthropic = true`. What it needs
to know is in [Configuration](/guide/config#models).

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

Every model has a limit on how much it can read at once, and ZettCode keeps a request inside it: `ctx 34.0%` in
the status line is how full it is, `/context` is the whole picture, and the request is compacted before it can
overflow, at `compact_percent` of the window. Setting the window and the trigger is in
[Configuration](/guide/config#models).

What each number on `/context` means, where the tokens go, what compaction costs and how to keep a request small
are in [The context window](/guide/context). Two things worth knowing here:

- The status line's `ctx` is the request as a share of the **window**; a `/context` row is a source as a share of
  the **request**. They are different denominators and a row can be 60% of one and 30% of the other.
- `compact_percent` is a fraction of the window, not of what is left: at 80%, a 200,000-token window is compacted
  from 160,000.

## Reading the status line {#reading-the-status-line}

`↑18.4k ↓900 · 71.2% cached · 74 tok/s · ctx 12.3%` — in order: tokens sent,
tokens generated, the share of the input the provider served from its cache,
generated tokens per second of streaming time, and how full the window was on the
newest request. Input/output totals accumulate across the session; context
occupancy is a snapshot, not an accumulated percentage.

| Field | How to read it |
| --- | --- |
| `↑` / `↓` | Cumulative input and output tokens reported by the provider. Repeated context counts as input each time it is sent. |
| `cached` | Cumulative cache-hit input tokens ÷ cumulative input tokens. 60,000 hits out of 100,000 input tokens is `60.0%`. |
| `tok/s` | Output tokens divided by the time the model spent streaming output, from its first fragment to its final response; not the wait for it to start, nor the time spent on tools, approvals, or reading the answer. |
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
