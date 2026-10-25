# Background agents

A daemon is a session with nobody at the keyboard. It runs in a workspace of its own, works while your terminal is
closed, and is reached the way every other session is reached: another agent sends it a message with
`send_message`, and it answers when it is done.

It is for work that should happen beside you rather than in front of you. A reviewer that reads a diff after you
wrote it, an explorer that goes through a failing test suite while you keep editing — each is a session that can be
started, listed and stopped:

```bash
zettcode daemon spawn --model gpt-5 --effort high
zettcode daemon list
zettcode daemon kill 01a1726a-3109-75a7-9285-390d9e381111
```

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
| `--model NAME` | The model to run on (default: the first configured) |
| `--effort LEVEL` | The reasoning level (default: the model's own) |
| `--resume SESSION` | Continue a stored session instead of starting empty |
| `--json` | Print the same facts as JSON, for a script or an agent |

`spawn` returns once the daemon is reachable — the id it prints can be messaged straight away. If it cannot start,
nothing is left behind and the reason is printed (the child's own first words are kept in
`~/.zettcode/daemon/<workspace>/.spawn/` until they are read).

::: warning A daemon runs with full shell permission
There is nobody to approve a command or answer a question, so a daemon never asks: shell commands run with your own
access, and a question from the model is declined. Start one only where you would run `--full` yourself.
:::

Its conversation is a new, empty one — the sender says what it needs to know. `--resume` picks up a stored session
instead, which is how a daemon continues work a killed one left, or how it reviews in a conversation you already had.
The session is an ordinary one: it is stored like any other, so after `daemon kill` you can `zettcode resume <id>` and
carry on by hand.

## Lists and stopping

`zettcode daemon list` shows every daemon on the machine, whichever workspace it works in:

```
SESSION                               WORKSPACE        MODEL  EFFORT  STATUS   FOR  TITLE
01a1726a-3109-75a7-9285-390d9e381111  ~/projects/api   gpt-5  high    idle     8m   Reviewer
01a1726b-2f41-75a7-9285-390d9e381112  ~/projects/web   gpt-5  low     working  2m   -
```

`STATUS` is `starting` (it has not joined the broker yet), `idle`, `working`, `stopping`, or `dead` — a dead entry is
one whose process is gone (the machine restarted, or it crashed); `kill` removes it. `--json` prints the same
fields for a program.

`zettcode daemon kill <session-id>...` stops each daemon and removes its record. The session stays, with everything it
did, so you can open it in the terminal afterwards.

## Talking to one

Nothing is typed into a daemon. Its input is `send_message`, from another session's agent or from the reader of a
terminal with `@`:

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
