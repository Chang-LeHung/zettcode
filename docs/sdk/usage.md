---
title: Usage and health
---

# Usage and health

The SDK can answer the two questions the terminal answers with `/usage` and `doctor`: what has been spent, and
whether the configured models work. Both read the same store the terminal does.

## What this session spent

`client.usage` is the current session's totals: input, output, cache reads, reasoning, requests, model seconds and
the context size of the newest call.

```python
import zettcode.sdk as zc

async with zc.Client(".") as client:
    spent = client.usage
    print(spent.input_tokens, spent.output_tokens, spent.total_tokens)
    print(spent.cache_hit_rate)      # the cached share of the input, or None
```

## What the workspace spent

`await client.usage_ledger()` returns everything the workspace's stored conversations recorded, laid out the way the
terminal's `/usage` page is: by session, by model and by day, with a total.

```python
async with zc.Client(".") as client:
    ledger = await client.usage_ledger()
    print(ledger.total.requests, ledger.total.total_tokens, ledger.total.cache_share)
    for session in ledger.sessions[:5]:
        print(session.id, session.title, session.entries, session.tokens.total_tokens)
    for model in ledger.models:
        print(model.model, model.tokens.requests)
```

The read is off the event loop, and the reader is kept on the client: a second look reads only the sessions that
changed since the first. Nothing is written to a session.

## One row of `/resume`

`await client.session_stats()` returns the stored totals of the current session; pass ids for others. Each row is
what the terminal's `/resume` panel shows: entries, replies, input, output, the cached share.

```python
async with zc.Client(".") as client:
    for stats in await client.session_stats([client.session.id]):
        print(stats.id, stats.entries, stats.requests, stats.total_tokens, stats.cache_share)
```

A session with no stored reply has no row; one that cannot be read is left out rather than raising.

## Is the model working?

`await client.check_models()` asks every configured model one short question, at once, and reports what each said —
the same check as `zettcode doctor`, without a session being written. A model that does not answer within the timeout
is reported, not raised.

```python
async with zc.Client(".") as client:
    for check in await client.check_models(timeout=15):
        print(check.model, check.ok, check.seconds, check.detail)
```

## What the model may compact itself

Self-compaction is the model deciding when to compact its own context. It has a configuration default and a
per-session choice, which the terminal's `/self-compact` panel edits:

```python
async with zc.Client(".") as client:
    print(client.self_compaction, client.self_compaction_choice)   # in force, and this session's own choice
    client.use_self_compaction(True)                               # this session may compact itself
    client.use_self_compaction(None)                               # follow the configuration again
```

The choice is stored in the session, so it is there when the conversation is reopened, and it applies from the next
request: the tool is offered when a request starts.

## `@` resources

`client.mentions(query)` lists what an `@` in a prompt can point at — the workspace's files, the skills on the search
paths, and whatever a plugin offers — for a completion menu:

```python
async with zc.Client(".") as client:
    for mention in client.mentions("cli", limit=5):
        print(mention.token, mention.kind, mention.description)
```

Prompts resolve `@` on their own with `mentions=True`; this is only the list a menu shows while the reader types.
