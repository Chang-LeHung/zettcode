# Background agents

A daemon is a session with nobody at the keyboard. It runs in a workspace of its own, works while your terminal is
closed, and is reached the way every other session is reached: another agent sends it a message with
`send_message`, and it answers when it is done.

It is for work that should happen beside you rather than in front of you. A reviewer that reads a diff after you
wrote it, an explorer that goes through a failing test suite while you keep editing — each is a session that can be
started, listed and stopped:

```bash
zettcode daemon model                    # what it can run on
zettcode daemon spawn --model gpt-5 --effort high
zettcode daemon list
zettcode daemon kill 01a1726a-3109-75a7-9285-390d9e381111
```

`daemon model` lists every model the configuration has, by the name `spawn --model` takes, with its id, API, whether
it takes images, its window and its reasoning levels; the first is marked `(default)` and is what a daemon runs on
when no model is given. `--json` prints the same fields for a script.

## Starting one

`zettcode daemon spawn` starts a background agent in the current directory and prints the session id it is messaged
by:

```
session  01a1726a-3109-75a7-9285-390d9e381111
workspace /Users/me/projects/api
model    gpt-5 · effort high

send_message(to="01a1726a-3109-75a7-9285-390d9e381111", message="...")
```

| Option | What it does |
| --- | --- |
| `-w DIR` | The directory it works in (default: the current one) |
| `--model NAME` | The model to run on, by the name `daemon model` lists (default: the first configured) |
| `--effort LEVEL` | The reasoning level (default: the model's own) |
| `-n LABEL`, `--name LABEL` | What this daemon is for, recorded beside the session and shown by `daemon list` (default: none) |
| `--title TEXT` | What to call the session (default: it names itself from its first answer) |
| `--permission LEVEL` | Its shell level: `safe` (every command in a sandbox), `deny` (no shell at all) or `full` (default). There is no `ask`: nobody is there to answer |
| `--resume SESSION` | Continue a stored session instead of starting empty |
| `--json` | Print the same facts as JSON, for a script or an agent |

`spawn` returns once the daemon is reachable — the id it prints can be messaged straight away. If it cannot start,
nothing is left behind and the reason is printed (the child's own first words are kept in
`~/.zettcode/daemon/<workspace>/.spawn/` until they are read).

::: warning A daemon asks nobody, and its shell level is its own
There is nobody to approve a command or answer a question, so a daemon never asks: `ask` is not a level it can be
given, and the `ask_user` tool is not offered at all. What the level you choose means:

- **`full` (the default)** — every command runs with the access of the account that started the daemon: no
  sandbox, no approval, no network restriction. Start one only in a workspace you would give a shell to.
- **`safe`** — every command runs in the sandbox: it writes only the workspace and the temporary directories,
  credentials under your home are hidden from it, and the environment is filtered down to `PATH`, `HOME`, `SHELL`,
  `LANG`, `TERM`, `TMPDIR` and the like. The network is **allowed**, so a sandboxed daemon can still fetch a
  dependency. `pip install --user`, `git push` over SSH and `gh` will fail.
- **`deny`** — no shell at all. The daemon reads files, edits them and talks, and never runs a command.

The configuration's own `permission` does not apply: a daemon's level is the one `spawn` was given.

Its conversation is still an ordinary session: what the daemon did with that access is in the session, and `daemon
list` shows what is running.
:::

Its conversation is a new, empty one — the sender says what it needs to know. `--resume` picks up a stored session
instead, which is how a daemon continues work a killed one left, or how it reviews in a conversation you already had.
The session is an ordinary one: it is stored like any other, so after `daemon kill` you can `zettcode resume <id>` and
carry on by hand.

## Lists and stopping

`zettcode daemon list` shows every daemon on the machine, whichever workspace it works in, one block each:

```
01a1726a-3109-75a7-9285-390d9e381111  idle  8m
  name       reviewer
  title      Reviewer
  workspace  ~/projects/api
  model      gpt-5 · effort high
  context    34k of 200k · 17%
  input      12.3k
  output     678
  shell      safe
```

The first line is the session id, what it is doing and how long: `starting` (it has not joined the broker yet),
`idle`, `working`, `stopping`, or `dead` — a dead entry is one whose process is gone (the machine restarted, or it
crashed); `kill` removes it. `name` is the label `spawn --name` recorded, and `title` the session's own name.
`context` is how full the context was on the newest call, the window it is measured against and the share of it;
`input` and `output` are what the session had sent and generated as of the daemon's last status change. `--json`
prints the same fields for a program.

`zettcode daemon kill <session-id>...` stops each daemon and removes its record. The session stays, with everything it
did, so you can open it in the terminal afterwards.

## Naming one

A daemon names itself: after its first answer the model writes a short title from that exchange, and `daemon list`,
`/resume` and `zettcode resume` all show it. A session that already has a title keeps it, so this is one model call
per session and not one per message.

`spawn --title` names the session from the start, and `daemon update` changes what is recorded afterwards:

```
zettcode daemon update 01a1726a-3109-75a7-9285-390d9e381111 --title "Auth refactor review"
zettcode daemon update 01a1726a-3109-75a7-9285-390d9e381111 --name reviewer
zettcode daemon update 01a1726a-3109-75a7-9285-390d9e381111 --name ""        # clear the label
```

`--name` is the daemon's label, and it may be changed at any time, including while the daemon runs: the daemon keeps
what a reader put there. `--title` is the *session's* name, and a session is written to only by the process that has
it open — so a running daemon refuses `--title` (stop it first; the daemon is already naming itself while it runs).
Given together, the label is written even if the title is refused, and the error says so.
`--json` prints the record afterwards.


## Talking to one

Nothing is typed into a daemon. Its input is `send_message`, from another session's agent — including the one your
terminal's model uses when you name the daemon with `@`:

```
send_message(to="01a1726a-3109-75a7-9285-390d9e381111", message="Review the diff of src/api.py, then say what you would change.")
```

The daemon takes one message at a time. While it is working, up to four more wait their turn; beyond that the sender
is told it is busy. It answers the same way — with `send_message(to=<your session id>, ...)` — so an agent that asked
something reads the answer as a message of its own.

A daemon never exits on its own, not even when it has been idle for hours: stop it with `daemon kill` when you are
done, or it stays there, listed, answering whenever someone writes.

## Where it is kept

```
~/.zettcode/sessions/<workspace>/<session-id>/    the conversation, like any other session
~/.zettcode/daemon/<workspace>/<session-id>/
    state.json                                    pid, status, model, effort, and when it started
    heartbeat                                     proof of life, rewritten every few seconds
    log                                           what went wrong, and the tools it ran
```

`~/.zettcode/daemon/<workspace>/workspace.txt` names the directory the folder belongs to, exactly as the session
store does. Removing a session's folder under `daemon/` is all `kill` does, besides stopping the process.

## A review to start with

The first thing most people want from a daemon is a second pair of eyes, and `/code-review` does the setup: it writes
a brief — collect the diff, have it read by a reviewer of its own, name concrete problems — and runs it as a turn of
the conversation, as if you had typed it.

```
/code-review
/code-review the error handling in src/api.py
```

What happens next is the model's: it looks at `<daemon> list` for a reviewer of this workspace — the one this
command names `code-review` — reuses it if there is one, and only otherwise starts a new one with `<daemon> spawn
--name code-review`. It sends that session what to read with `send_message`, and reports the answer when it arrives
as a message. A reviewer that has already read the earlier rounds knows the change, which is why it is preferred to
a fresh one; the name and the workspace are what `list` says, so a reviewer from another terminal on the same
workspace is the one reused.

The reviewer stays up while the fixes are made: the main agent changes what it found, sends it the new state of the
change, and goes round again until the reviewer has nothing left to say. Every message to it says that it must
answer — findings, or a word that there is nothing to change — because a reviewer that goes quiet cannot be told
apart from one whose review found nothing. A round that brings no answer is sent once more; if that is unanswered
too, the reviewer's own conversation is read instead — `~/.zettcode/sessions/*/<session id>/data.jsonl`, whose last
assistant message is its review — that is reported, and the reviewer is stopped with `<daemon> kill <session id>` so
that it is not left running; `<daemon> list` shows what is.

`<daemon>` is the command of the installation the terminal itself runs on — `python -m zettcode.daemon` under the
same interpreter — not a `zettcode` looked up on the `PATH`, so a checkout or a virtualenv that nothing else can see
still starts one.

The reviewer runs at **your own shell level**, never above it: `full` gives it `full`, `safe` gives it `safe`, and a
session at `ask` — a level that means "ask the reader", which a background process cannot do — gives it `safe`. Under
`deny` there is no shell to gather a diff with, so no reviewer is started and the model reviews by reading. The
reviewer is told that it reads and does not change — the edits are the main agent's, made after the findings are in —
but that is an instruction, not a sandbox: a reviewer at `full` could change things if it chose to.
