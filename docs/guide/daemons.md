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
shell    full

send_message(to="01a1726a-3109-75a7-9285-390d9e381111", message="...")
```

| Option | What it does |
| --- | --- |
| `-w DIR` | The directory it works in (default: the current one) |
| `--model NAME` | The model to run on, by the name `daemon model` lists (default: the first configured) |
| `--effort LEVEL` | The reasoning level (default: the middle of the ones the model takes) |
| `-n LABEL`, `--name LABEL` | What this daemon is for, recorded beside the session and shown by `daemon list` (default: none) |
| `--title TEXT` | What to call the session (default: it names itself from its first answer) |
| `--permission LEVEL` | Its shell level: `safe` (every command in a sandbox), `deny` (no shell at all) or `full` (default). There is no `ask`: nobody is there to answer |
| `--resume SESSION` | Continue a stored session instead of starting empty |
| `--json` | Print the same facts as JSON, for a script or an agent |

An installed plugin may add its own options to this command; they are listed by `zettcode daemon spawn --help` and
reach the plugin as the `PLUGIN_CLI` service. `spawn` returns once the daemon is reachable — the id it prints can be messaged straight away. If it cannot start,
nothing is left behind and the reason is printed (the child's own first words are kept in
`~/.zettcode/daemon/<workspace>/.spawn/` until they are read).

::: warning A daemon asks nobody, and its shell level is its own
There is nobody to approve a command or answer a question, so a daemon never asks: `ask` is not a level it can be
given, and the `ask_user` tool is not offered at all. What the level you choose means:

- **`full` (the default)** — every command runs with the access of the account that started the daemon: no
  sandbox, no approval, no network restriction. Start one only in a workspace you would give a shell to.
- **`safe`** — every command runs in the sandbox: it writes only the workspace and the temporary directories,
  credentials under your home are hidden from it, and the environment is filtered down to `PATH`, `HOME`, `SHELL`,
  `LANG`, `TERM`, `TMPDIR` and the like. The network follows `[shell] network` in the configuration, off by
  default, as it does for a terminal; turn it on there if the daemon must fetch a dependency. `pip install --user`, `git push` over SSH and `gh` will fail.
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
`input` and `output` are what the session had sent and generated; they are written when the daemon changes status and,
while a turn runs, whenever a number moved (checked every few seconds). The figures are as of the last completed
model call, so they do not tick while one answer is still streaming. A `next`
line appears while a model or level a reader asked for is waiting to be taken up, and an `error` line says why the
last request could not be met. A `broker` line appears while the daemon cannot reach the session broker — it keeps
trying, and so cannot be messaged meanwhile. `--json` prints the same fields for a program.

`zettcode daemon stop <session-id>...` stops each daemon but keeps its record, shown as `dead`, so it stays in
`daemon list` and the gateway's list and can be started again with `spawn --resume`.
`zettcode daemon kill <session-id>...` stops it and removes the record. Both refuse a daemon that is in the middle of
a turn, because stopping it throws the turn away; add `--force` to stop it anyway. The session stays either way, with
everything it did, so you can open it in the terminal afterwards.

`zettcode daemon delete <session-id>...` removes a daemon for good: its record **and its conversation**. It cannot be
undone, and a daemon that is still running is refused — stop it first. Use it when the list has grown long.

`zettcode daemon log <session-id>` prints the last lines the daemon wrote about itself — the tools it ran, the turns
that failed, the settings it took up — and `-n N` says how many. A daemon that seems stuck is diagnosed there first.

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

## Changing what it runs on

A running daemon can be moved to another configured model, or another reasoning level, without losing the
conversation; the change is in force from its next turn (and while it is idle, within a few seconds):

```
zettcode daemon update 01a1726a-3109-75a7-9285-390d9e381111 --model gpt-5 --effort high
```

The model may be named as `daemon model` lists it, or by its id. A model this machine does not have is refused, and
so is a level the model does not take. A daemon that is not running cannot be moved: start the next one with the
model and level it should use. While the request is pending, `daemon list` shows it on a `next` line; if the daemon
cannot take it up (the configuration it was started with differs from yours, say), it says so on an `error` line
and the request is not tried again.

`--effort` is the level the model takes, and the one a daemon starts at when nobody names one is the **middle of
that model's list**: providers do not all accept every level, and the middle is the answer that means "as much as
this model does by default" whichever list it publishes. For the eight levels zettcode knows, that is `high`.

## Changing its shell level

A shell level is given to the process when it starts, so changing one is a restart, not a request:

```
zettcode daemon update 01a1726a-3109-75a7-9285-390d9e381111 --permission safe
```

The session survives it — the daemon is started again with `--resume`, so its conversation and history are the
ones it had — and the turn in flight does not, which is why a daemon in the middle of one is refused: wait for it to
finish, or stop it and start it again yourself. `daemon list` shows the level on its `shell` line.


## Talking to one

Nothing is typed into a daemon. Its input is `send_message`, from another session's agent — including the one your
terminal's model uses when you name the daemon with `@`:

```
send_message(to="01a1726a-3109-75a7-9285-390d9e381111", message="Review the diff of src/api.py, then say what you would change.")
```

The daemon takes one message at a time. While it is working, up to 64 more wait their turn, and when it becomes free
it takes everything that waited as **one** turn, each message under its own line saying who sent it. Past 64 the
broker keeps the message and hands it over as soon as there is room, so the sender is not told to try again. It answers
the same way — with `send_message(to=<your session id>, ...)` — so an agent that asked
something reads the answer as a message of its own.

The command line is a sender too, for a prompt you want to give without opening a session:

```
zettcode daemon prompt 01a1726a-3109-75a7-9285-390d9e381111 "Review the diff of src/api.py, then say what you would change."
```

It goes through the session broker like any other message. The sender is a name rather than a session, so the daemon
does not answer back: its turn is stored in its own session, which `zettcode resume <id>` opens and `daemon log` says
what it did.

A daemon never exits on its own, not even when it has been idle for hours: stop it with `daemon kill` when you are
done, or it stays there, listed, answering whenever someone writes.

## When a turn fails

A turn that failed in a way that may pass — a timeout, a dropped connection, a rate limit, a server error — is
tried again, up to three times, with a short wait between tries (about seven seconds in all, so a rate limit that
lasts longer will still end in a failure). A retry continues the request where it stopped rather than sending the
prompt again, so the model is told which tools were cut short and decides; a tool is never run twice on its own. A
failure that would fail again (a wrong key, a model that is not there) is not retried.

If the turn still fails, the sender is told when it can be: a chat window sees the failure line, and a session that
sent a message gets a reply saying the turn failed and why. `daemon prompt` speaks as a name rather than a session,
so it cannot be answered — the reason is in the log. The daemon itself keeps running and takes the next message;
`daemon list` shows it `idle` again, and `daemon log <id>` is where the attempts it made and the last reason are.

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

The first thing most people want from a daemon is a second pair of eyes. `/code-review` starts (or reuses) a daemon
named `code-review` for it. How the command works, step by step, and the shell level the reviewer gets, are on
[Code review](/guide/code-review).
