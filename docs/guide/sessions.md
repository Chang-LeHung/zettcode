# Sessions

A session is a conversation with a workspace: what was asked, what was answered,
which tools ran. ZettCode writes each one down as it happens, so leaving is never
losing work.

## Where they live

One store root holds every workspace, grouped by workspace first:

```
~/.zettcode/sessions/<workspace key>/
├── metadata.jsonl              the index: titles and activity times
└── <session-id>/
    └── data.jsonl              the conversation
```

`<workspace key>` is the URL-safe base64 of the resolved workspace path, so two
checkouts of the same project never share a folder, and no path can escape the
store.

`data.jsonl` is append-only — every record names its parent, which makes the
conversation a **tree** rather than a list. `metadata.jsonl` is the small index
the session list reads, so showing recent sessions never parses a conversation.
A crash can truncate the final line; that line is ignored, and a damaged line
anywhere else is reported rather than silently dropped.

::: tip Why a tree
Appending is the only write, so saving a turn cannot rewrite history. It also
buys two things you can see: **resuming** is just walking from the newest record
back to the root, and **compaction** adds a summary that later requests stop at,
without deleting anything.
:::

## Leaving and coming back

On exit the shell prints the way back in:

```
resume this session: zettcode --resume 01a10b75 --workspace ~/projects/api
```

Inside the program, `/resume` opens a panel of recent sessions for this
workspace, newest first, each with its title and how long ago it changed;
`/resume <id>` skips the panel. The status line names the session you are in.

`/new` starts a fresh one and leaves the current conversation on disk. `/clear`
only empties the screen; the session keeps going, and the model still remembers
the turns.

## Titles

After the first reply, the agent asks a small model call for a four-or-five word
name and appends it to `metadata.jsonl`. That is what the sessions panel and the
status line show.

`/title users endpoint` names it yourself, and the name sticks: the automatic
naming never overwrites a session that already has a title, so a name you chose
before the first message survives it.

## Exporting

`/export report.html` writes the session — every turn, the tool calls, the
timings, the compaction summaries, and the active context — to one standalone
HTML file you can read in a browser, keep as a record, or paste into a review.
Without a path it lands in the workspace as `zettcode-<session-id>.html`, and
the shell prints where.

The page is a sidebar of turns with the selected turn's events on the right,
each carrying the text it was written with, when it was written, and what it
cost. Long text — the system prompt, a wall of tool output — starts collapsed
and opens into a block that scrolls instead of stretching the page. The last
entry in the sidebar is the **current context**, so the file answers both "what
was said" and "what the model is carrying now"; a compacted session shows its
checkpoint there, and a system instruction that repeats is pointed at rather
than printed again.

The exported page needs no network and no server: styles and script are inlined.
