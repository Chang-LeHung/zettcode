# Token usage

`/usage` shows what this project has spent: every session in it, every model it ran on, and every day it was used. It
reads the conversations stored on this machine: it is not a bill and not a live meter.

```text
/usage
```

`Tab` or `1`, `2`, `3` switch views; `Esc` or `q` closes. It covers the project you launched in: `zettcode -w
~/projects/api` counts that project and leaves the others alone.

## The three views

| View | Answers | Ordered by |
| --- | --- | --- |
| **Models** | Which model sent and generated what | Largest first |
| **Sessions** | What each conversation cost, and how much of its input the cache served | Last changed first |
| **Calendar** | Which days you worked, and how heavy each was | One column per week |

## What is counted

| Word | What it counts |
| --- | --- |
| `in` | Every token **sent**. A conversation is sent again each turn, so the same older messages are counted again. |
| `out` | Every token **generated**, reasoning included. |
| `cached` | The part of `in` the provider answered from its cache, billed more cheaply. A share of `in`, not a count. |
| `reasoning` | The part of `out` the provider counted as thinking. A share of `out`. |
| tokens | `in` + `out`. Cache and reasoning are already inside those two. |
| requests | Model calls: one per turn, plus the ones compaction made. |
| sessions | Conversations counted, one row in `/resume` each. |

Counts are short above a thousand: `740K`, `3.14M`. Every number is a counter the provider reported; nothing is
estimated here.

One line above all three views totals the project:

```text
All models   3.14M tokens   in 2.98M   out 159K   cached 61.07%   43 requests · 3 sessions
```

Read right to left: 43 calls across 3 sessions, 159,000 tokens generated, 61.07% of the input from cache. `cached`
always carries two decimals; a dash means the provider reported no cache read, as many local endpoints do.

## Reading the bars

![The /usage page on the Models tab, with a bar row for each model](/screens/usage-models.svg)

**Models** gives input and output their own scales, each against the biggest model: output is a small fraction of
input, so a shared scale would draw it as nothing.

![The Sessions tab: four times, a title, two token bars and a cache bar per row](/screens/usage-sessions.svg)

**Sessions** puts the token bars on a square-root scale, so a session a thousand times smaller is still visible beside
the biggest one; the numbers beside them are exact. The cache bar is a plain 0–100%, so two rows compare directly.

The cache share is the column worth reading twice. A long session you keep returning to tends to keep it high, because
its beginning stays cached; a short one that always starts where another stopped tends to be lower. Model switches,
compaction and long idle gaps all lower it. There is no good value: compare a session with itself after a change, not
with its neighbour.

![The Calendar tab: weeks as columns, weekdays as rows, days shaded by what they spent](/screens/usage-calendar.svg)

**Calendar** is a column per week, Sunday to Saturday, a row per weekday, and a square per day, shaded by that day's
tokens. Four shades and a blank cover every day, cut at the quartiles of the days you used, so the grid shows the shape
of your work and not its size: a thousand tokens a day and a million both get dark and pale days. A future day is not
drawn. Look at the key before the grid — a shade easy to see in one palette can be faint in another.

Under the grid, the chosen day's line, then `active days`, `longest streak`, `current streak` and `busiest`. `←` `→`
move the chosen day by a week, `↑` `↓` by a day.

## Where the numbers come from

The first `/usage` reads every stored conversation, which can take seconds for gigabytes of them. It then keeps a small
`usage.json` beside that project's sessions, under `~/.zettcode/sessions`, and later runs read only what was added.
Delete it and the next `/usage` rebuilds it. `/resume` reads a smaller `sessions.json` beside it, one line per session.

- **A reply is counted once**, in the session it was first written in. `/fork` copies the conversation, and a fork
  shows only what it spent afterwards.
- **A subagent's session is not counted.** Its tokens appear in the turn that asked for it.
- **A day is a day in your time zone.**
- **Compaction counts**, because it is a model call.
- **An older session counts** when its replies carry usage; a reply without it adds nothing rather than a guess.

## This page, or the status line?

`/usage` covers every session stored in the project, so far; the status line counts this session, since it began. Its
`cached` share is the project's input; the line's is this session's. A session that looks modest in the status line can
still be a large row here, and neither is a bill: check the provider's dashboard for what was charged. See
[Reading the status line](/guide/models#reading-the-status-line).

## When something looks wrong

| What you see | What it means |
| --- | --- |
| The page is empty | No session here has a reply with usage. A request stopped before an answer spent nothing. |
| A number much larger than the conversation | Input is counted again every time it is sent. |
| A day looks too light or too dark | The shades are quartiles of your own days; one heavy day reshades the rest. |

## Next steps

- [The context window](/guide/context): what one request carries.
- [Sessions](/guide/sessions): where a conversation is stored and how to resume it.
- [Configuration](/guide/config#models): the model keys these totals belong to.
