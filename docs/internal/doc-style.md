# How the guide is written

The guide exists so a reader can get something done with the least reading. Judge every page by that, not by how much
it explains.

## Rules

1. **One page, one job.** Say the job in the first sentence. Two unrelated jobs mean two pages.
2. **The first screen answers three questions:** what this is, who it is for, and the one command or decision that
   follows. Keep it under 100 words before that command.
3. **Tutorial pages use verb headings** — Install, Connect a model, Start a task. Reference pages use nouns.
4. **One canonical path.** Alternatives (pip/uv, macOS/Windows) go in tabs or a short table, never in the flow.
5. **One sentence before a command, one after it.** The second says what the command did, not that it matters.
6. **Second person, present tense, imperative.** One idea per sentence, 25 words at most. Cut "simply", "just",
   "note that", "it is worth mentioning", "in order to".
7. **Explain why only when it changes what the reader does.** Internals, file layouts and design rationale belong in
   `docs/internal/` or a linked reference page.
8. **A feature gets four lines:** what it is, when to use it, the command, the detail link. Not a tour of its insides.
9. **Reference pages are tables first.** Prose only for defaults, exceptions and common mistakes.
10. **No repeated explanation.** Every fact has one home; every other page links to it.
11. **End with next steps.** Two to four links, not a summary of what was just read.
12. **Chinese mirrors the English structure and budget.** It is a rewrite, not a literal translation.

## Page budgets

| Kind | Words | Pages |
| --- | --- | --- |
| Front door | 300–700 | README, overview, getting-started |
| Feature | 500–1,200 | interface, commands, sessions, context, faq |
| Reference | 1,500–3,000; an API reference may be longer | config, commands, plugin API |

Over budget means move detail to the linked reference page, or delete it. The reference page may be long; it must be
scannable, with a table for every enumerable set.

## Shape

A feature page:

```markdown
# Sessions

A session is one conversation, stored so you can come back to it.

## Resume one

Open a stored session instead of starting fresh.

    zettcode -r <session>

## What is saved

| … | … |

## Next steps

- [Commands](/guide/commands)
- [The context window](/guide/context)
```

A reference page: the first table within the first screen, one sentence of lead-in per table, no storytelling.

## Before and after

Bad:

> ZettCode maintains a persistent conversation per session. When a request is assembled, the runtime counts the
> messages, the tool schemas and the environment notes with a local tokenizer, and the provider reports its own
> count for what it billed, so the two numbers can differ.

Good:

> `/context` shows how full the model's window is. The total is what the provider billed; the split between sources
> is estimated locally, so read it as a proportion, not a measurement.

Bad:

> The following section describes the various configuration options that are available to you.

Good:

> Add a model:
