# Sessions

A session is a conversation with a workspace: what was asked, what was answered,
which tools ran. ZettCode saves conversation events as they arrive. A normal
exit does not delete the saved session.

## Where they live

One store root holds every workspace, grouped by workspace first:

```
~/.zettcode/sessions/<workspace key>/
└── <session-id>/
    ├── data.jsonl              the conversation
    ├── metadata.json           the title, the times and the model: a couple of hundred bytes
    ├── session.lock            held by the process that has the session open
    └── tool-output/            what long shell commands printed, kept for the model to read
```

`<workspace key>` is the resolved workspace path with a `-` between its levels —
`/Users/me/projects/api` is `-Users-me-projects-api` — so a glance at the folder
list says which project is which, and no path can escape the store. Any other
character a folder name cannot hold becomes a `-` too, and a very long path keeps
a short digest instead of its tail. Joining with a dash can read the same for two
paths (`/a-b/c` and `/a/b-c`); the folder records the path it belongs to in
`workspace.txt`, and the project that finds the name taken keeps using a folder
named with the URL-safe base64 of its path, which is always its own.

`data.jsonl` is append-only — every record names its parent, which makes the
conversation a **tree** rather than a list. `metadata.json` is the small file the
session list reads, so showing recent sessions never parses a conversation. It is
written when a session starts, when it is renamed, and when the model it uses
changes — not on every message — so it stays the same size however long the conversation
gets, and it travels with the folder if you copy or move it. How recently a session was used comes from the
conversation file itself. A crash can truncate the final line; that line is
ignored, and a damaged line anywhere else is reported rather than silently dropped.

A session that never got a message leaves nothing behind. Opening ZettCode in a project
creates no folder for it until something is first stored, quitting an unused session
removes its folder (and the project's, if that leaves it empty), and the next start sweeps
the empty folders that a killed terminal could not tidy — never one that another ZettCode
has open. A session you named with `/title` has a title to keep, so it stays.

::: details Sessions from an older version
Older versions named the workspace folder with the URL-safe base64 of the path
(`L1VzZXJzL21l…`). The first time ZettCode opens such a workspace it renames the
folder to the readable name, in one step, so nothing is copied and nothing is ever
half-moved. If the rename cannot be done — a session in it is open in another
ZettCode, or a file in it is open and the system refuses (Windows does) — the
folder keeps its old name and is used exactly as before; the next start tries again.

Older versions kept one `metadata.jsonl` for the whole workspace and added a line to
it for every message, so it could reach thousands of lines. Nothing writes it any
more. The first time ZettCode looks at a session that has no `metadata.json` of its
own, it reads what that file recorded — the title and the times — and saves it into
the session's folder, so each old session is carried over once and the old file is
not consulted for it again. The old file is left in place and is never modified; you
can delete it once you no longer need to go back to an older version. A
`metadata.json` that is damaged, or that belongs to a different session (a folder
copied under a new name), is simply rebuilt.
:::

### Which model a session uses

Each session remembers the model it last used. When a turn ends — however it ends, a stopped
or failed turn used the model too — ZettCode writes that model's name into the session's
`metadata.json` if it is not already there, so switching models costs one small write and an
ordinary message costs none.

Resuming the session — `/resume`, `/fork`, or `zettcode --resume` — switches back to that
model, and the conversation says so:

```text
──────── Model set to GPT-4o, the one this session last used. ────────
```

- Switching with `/model` is not "using": nothing is recorded until a message is sent on it.
- A `/btw` side question is not part of the conversation and records nothing.
- A session that never recorded a model — one from an older version, or one that has not had a
  turn yet — keeps whichever model is selected when you open it.
- If the recorded model is no longer in your configuration, or two entries show the same name so
  ZettCode cannot tell which was meant, it stays on the current model and says so
  (`This session last used … which is not in your configuration; staying on …`) instead of
  guessing.
- The name recorded is the one the model picker shows (`display_model` when you set one). If you
  edit the configuration between runs — adding a `display_model` to an entry that had none, say —
  a session recorded under the old name still finds it.
- `/fork` starts on the model the original was using.

### Long command output

When a shell command prints more than fits in a reply, the model is shown the start and
the end and told where the whole output is. That output is kept in the session's own
`tool-output/` folder under `~/.zettcode`, not in your project, so it never turns up in
`git status` or a search. It is removed along with the session. Folders named
`.zett-tool-output` that earlier versions left in your projects are not moved or deleted;
they are safe to delete (and to add to `.gitignore`).

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
`/resume <id>` skips the panel. The header names the session you are in.

`/new` starts a fresh one and leaves the current conversation on disk. `/clear`
only empties the screen; the session keeps going, and the model still remembers
the turns.

### Example: continue yesterday's work

Start in the same workspace, then choose a session:

```bash
zettcode -w ~/projects/api
```

Inside ZettCode, type `/resume`, use `Up` / `Down` to highlight the conversation,
and press `Enter`. Its earlier messages replace the current transcript; you can
then send "Continue from the last failing test."

If you already have the id, skip the picker:

```bash
zettcode --workspace ~/projects/api --resume 01a10b75
```

Replace both the path and id with your own. A plain `zettcode` always starts a
new session; it does not silently reopen the last one. If the id is not found,
check the workspace first: two checkouts have separate session lists even when
their files are identical.

## One process at a time

A session can be open in one ZettCode process at a time. Opening it takes a **lock** — an operating-system lock on
`session.lock` in the session's folder — and the process that holds it is the only one that writes to the session.
Without it, two terminals resumed on the same session would each append to it from their own idea of where the
conversation had got to, and the conversation would fork behind both of them.

The lock goes with the process, however it ends: closing ZettCode, a crash and `kill -9` all release it, so there is
never a stale lock to clear by hand. Starting a new session, resuming or forking moves it.

If you resume a session another process has open, you can still **read** it, but the composer is replaced by a small
padlock and the words "read-only", with no arrow and no hint:

```text
  ◈ zettcode  Fix the parser · ~/projects/api
  …the conversation, as it was when you opened it…

 ┌──────────────────────────────────────────────────────┐
 │                          🔒                          │
 └──────────────────────────────────────────────────────┘
   ● ready
```

- **What it takes.** Only slash commands: type `/` and a small `⊘` takes the arrow's place. Anything else is
  not accepted, including a paste or a picture, and `Backspace` still clears what was there.
- **What it refuses.** Anything that writes to the session: a message, `/btw`, `/title`, `/compact`, and the title
  the first answer would have written. A locked session also does not appear to the other sessions for
  [messaging](/guide/messaging), so nobody can send it something it would have to turn into a write.
- **Getting out.** `/new` starts a session of your own, and `/fork` carries this conversation into one. Or wait:
  ZettCode tries again every couple of seconds, and the moment the other process lets go it **reads the session
  again** — so what that process wrote is on screen — and unlocks the composer. Pressing `Enter` on the padlock tries at
  once.

## Forking

`/fork` carries the conversation into a new session and continues there. Reach for
it when you want to take a different direction without losing the one that got you
here: the session you were in is not touched — every message stays where it is —
and the fork is a second conversation that starts from where that one had got to.

What is carried is what a request would send: the newest compaction summary and the
messages after it. A conversation that was compacted therefore forks into the part
of it the model is still reading, rather than into a file of messages that were
summarized away and would be walked past on every later turn. The fork records the
session it came from and takes its title with `(fork)` after it, so the session
list shows the two apart.

The fork says all of this in the conversation, so nothing has to be remembered:

```text
Forked into a new session: "Fix the parser (fork)" · 01a12dd8-2d6d-70b2
resume this session: /resume 01a12dd8-2d6d-70b2
back to the previous session: /resume 01a10b75-c3a1-4d2e · "Parser rewrite"
from a shell: zettcode --resume <session id> --workspace ~/projects/api
```

The session you left is named with it, because that is where the work which led here
lives: going back to it is one `/resume` away, and this line is the only place its id
is written down. Both in-app commands are named because they are wanted at different
moments, and the command-line form carries a placeholder id — either session fits —
together with the workspace, since the store is keyed by workspace and an id on its
own means nothing in another checkout.

## Titles

After the first reply, the agent asks a small model call for a four-or-five word
name and saves it in the session's `metadata.json`. That is what the sessions panel
and the header show.

`/title users endpoint` names it yourself, and the name sticks: the automatic
naming never overwrites a session that already has a title, so a name you chose
before the first message survives it.

For example, type `/title Fix users pagination`. Type `/title` without an
argument to report the current title. An untitled session is displayed as
`New session`; naming it makes a long list easier to scan.

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

### Example: save and share a report

Type `/export review.html` inside ZettCode, then open the reported file from
your file manager or browser. A relative path is relative to the workspace;
an absolute path lets you choose a different directory. Parent directories
are created when needed.

`/btw` exchanges are not included in either the exported history or exported
model context, although they do reappear in the transcript when you resume.
The export is a snapshot; it does not update when you continue the session.
It also is not a session backup you can import through `/resume`.

::: warning Review before sharing
An export can contain source code, prompts, file paths, and tool output with
private information. Inspect it before sending it to someone else. To back up
resumable sessions, copy the workspace's session-store directory instead.
:::
