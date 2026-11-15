# Sessions

A session is one conversation, saved so you can come back to it: what you asked, what was answered, which tools
ran. Events are written as they arrive, and an ordinary exit does not delete them.

## Where they live

Everything sits under `~/.zettcode/sessions`, grouped by workspace first:

| Path | What it holds |
| --- | --- |
| `<workspace key>/` | One folder per workspace: its resolved path with `-` between the levels, so `/Users/me/projects/api` is `-Users-me-projects-api`. |
| `<id>/data.jsonl` | The conversation, append-only. Every record names its parent, so it is a tree: resuming walks it back to the root, and compaction adds a summary without deleting anything. |
| `<id>/metadata.json` | Title, times and model. Written when a session starts, is renamed, or changes model — not per message, so the list never parses a conversation. |
| `<id>/session.lock` | Held by the process that has the session open. |
| `<id>/tool-output/` | Long command output, kept out of your project. |

A session that never got a message leaves nothing behind: an unused session's folder goes when you quit, and the
next start sweeps the ones a killed terminal left empty. A session you named with `/title` stays.

Resuming puts back the model and the reasoning level the session last used, and the conversation says so. Every
case around that — a model no longer configured, a level the model does not take — is in
[Models and context](/guide/models).

## Coming back

On exit the shell prints the way back in, so the return trip is one copy and paste:

```
resume this session: zettcode resume 01a10b75 --workspace ~/projects/api
```

| From | Command |
| --- | --- |
| Inside ZettCode, from a list | `/resume` |
| Inside ZettCode, by id | `/resume 01a10b75` |
| From a shell | `zettcode -r 01a10b75 -w ~/projects/api` |

The `/resume` panel lists this workspace's recent sessions, newest first, with a search box that filters by title or
id as you type. A plain `zettcode` always starts a new session; it never reopens the last one. Two checkouts keep
separate lists even when their files are identical, so check the workspace before hunting for a missing id.

`/new` starts a fresh session and leaves the current one on disk. `/clear` only empties the screen; the session and
its memory of the turns go on.

## Forking

`/fork` carries the conversation into a new session and continues there. The session you were in is not touched —
every message stays where it is — so a fork is how you take a different direction without losing the one that got
you here. What it carries is what a request would send: the newest compaction summary and the messages after it. The
fork takes the origin's title with `(fork)` after it, and the conversation names both sessions and the commands that
return to either.

## Titles

After the first reply the agent asks a small model for a four-or-five word name and saves it. `/title users
endpoint` names the session yourself, and the automatic naming never overwrites a name you chose. `/title` on its
own reports the current one. An untitled session shows as `New session`.

## Exporting {#exporting}

`/export report.html` writes the session — every turn, the tool calls, the timings, the compaction summaries and the
active context — to one standalone HTML file. Styles and script are inlined, so it needs no network and no server.
Without a path it lands in the workspace as `zettcode-<session-id>.html` and the shell prints where; a relative path
is relative to the workspace.

The page is a sidebar of turns, with the selected turn's events on the right and the current context as the last
entry. A `/btw` exchange is not included. The file is a snapshot, and not a backup you can resume from: to keep
resumable sessions, copy the workspace's folder under `~/.zettcode/sessions`.

::: warning
An export can contain source code, prompts, file paths, and tool output with private information. Read it before you
send it to anyone.
:::

## One process at a time

A session is open in one ZettCode process at a time. Opening it takes an operating-system lock on `session.lock`,
and only the holder writes; without that, two terminals resumed on one session would each append from their own idea
of where the conversation had got to. The lock goes with the process however it ends, so there is never a stale one
to clear by hand.

If you resume a session another process holds, you can read it, but the composer is replaced by a padlock and the
words "read-only". Slash commands still work; anything that writes to the session is refused, including a message,
`/btw`, `/title` and `/compact`, and the session is not offered to [`@` messages](/guide/messaging). `/new` starts a
session of your own and `/fork` carries this conversation into one. ZettCode also retries every couple of seconds and
reads the session again the moment the other process lets go; `Enter` on the padlock tries at once.

## Long output

A shell command that prints more than fits in a reply is shown to the model at its start and end, with a note of
where the whole output is. A tool that is not one of ZettCode's own — an MCP server, a subagent, a plugin — is held
to the same rule, so one long answer cannot fill the rest of the session. The output is kept in the session's
`tool-output/` folder, never in your project, so it does not turn up in `git status` or a search, and it goes when
the session goes. Folders named `.zett-tool-output` that older versions left behind are safe to delete.

## Next steps

- [Commands](/guide/commands): every slash command, and the `zettcode` command line.
- [The context window](/guide/context): what a session carries, and when it is compacted.
- [Token usage](/guide/usage): what this project's sessions have spent.
