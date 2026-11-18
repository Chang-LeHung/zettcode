# Background agents

A daemon is a session with nobody at the keyboard. It works in a workspace of its own while your terminal is closed,
and you reach it by sending it a message. Use it for work that should happen beside you: a reviewer that reads a diff,
an explorer that runs the failing tests while you keep editing.

## Start one

```bash
zettcode daemon spawn --name builder --title "tool builder" --permission safe
```

It prints the session id. The daemon is reachable as soon as `spawn` returns.

| Option | What it does |
| --- | --- |
| `-w DIR` | The directory it works in (default: current). |
| `--model NAME` | A model from `zettcode daemon model` (default: the first configured). |
| `--effort LEVEL` | The reasoning level (default: the middle of what the model takes). |
| `-n`, `--name LABEL` | A label for `daemon list`. |
| `--title TEXT` | The session's name; otherwise it names itself after the first answer. |
| `--permission LEVEL` | `safe`, `deny` or `full` (default). There is no `ask`. |
| `--resume SESSION` | Continue a stored session instead of starting empty. |
| `--json` | Print the same facts as JSON. |

Nobody approves a daemon's commands, so its shell level matters:

- `full` (default): every command runs with your access, no sandbox, network allowed. Use it only in a workspace you
  would give a shell to.
- `safe`: every command runs in the sandbox, which writes only the workspace and temporary directories; the network
  follows `[shell] network` (off by default). `pip install --user`, `git push` over SSH and `gh` will fail.
- `deny`: no shell at all; it reads, edits and talks.

A daemon's conversation is an ordinary stored session. After `daemon kill` you can `zettcode resume <id>` and carry on
by hand.

## Talk to one

Name it with `@` in your prompt, or send from another session's model with `send_message(to="<id>", message="...")`.
From a shell, `zettcode daemon prompt <id> "..."` sends one message without opening a session; the daemon does not
answer a shell sender, but the turn is stored.

A daemon handles one message at a time. While it works, up to 64 wait and then run together as one turn, each under a
line saying who sent it; past 64 the broker holds the message until there is room. It answers with `send_message`, so
the asking session reads the answer as a message of its own. A turn that failed in a way that may pass — a timeout, a
dropped connection, a rate limit — is retried up to three times from where it stopped.

## Manage one

| Command | What it does |
| --- | --- |
| `zettcode daemon list` | Every daemon on the machine: status, workspace, model, context, shell. |
| `zettcode daemon log <id>` | The last lines it wrote about itself; `-n N` sets how many. |
| `zettcode daemon stop <id>` | Stop it and keep its record (shown as `dead`); `spawn --resume` starts it again. |
| `zettcode daemon kill <id>` | Stop it and remove its record. The session stays. |
| `zettcode daemon delete <id>` | Remove the record and the conversation. Cannot be undone. |
| `zettcode daemon update <id>` | Change `--model`, `--effort`, `--name`, `--title`, or `--permission`. |
| `zettcode daemon model` | List the models `spawn --model` accepts; `--json` for scripts. |

A daemon that exits any other way, such as a reboot or Ctrl-C, keeps its record too: it is listed as `dead` in
`daemon list`, in `/hub` (Daemons tab) and in the gateway's chats, and can be started again from any of them. Only
`kill` and `delete` remove it.

![The /hub page on the Daemons tab: three daemons with their state, age, title, model and workspace, and the keys that act on the marked row](/screens/hub.svg)

`/hub` is the same list without leaving the conversation: `Tab` walks Graph, Sessions, Daemons and History, and the
row under the mark takes one of four keys.

| Key | On the Daemons tab |
| --- | --- |
| `Enter` | Start the daemon; an offline one resumes its session. |
| `t` | Restart it — a running one is stopped first. |
| `s` | Stop it and **keep** its record, shown as `idle`. |
| `d` | Delete the record **and its conversation**. Two presses: the first asks, any other key forgets. |

`/` searches the tab, `r` reads the machine again, and `Esc` clears the search before it closes the page.

`stop` and `kill` refuse a daemon in the middle of a turn; add `--force` to stop it anyway. A model or effort change
takes effect from the next turn. A permission change restarts the process, so the turn in flight is lost. `--title`
is refused while it runs, because the running process owns the session's name.

## Next steps

- [Talking between sessions](/guide/messaging): messages, groups and the broker.
- [Web gateway](/guide/gateway): start, watch and stop daemons from a page.
- [Codex & Claude Code](/guide/code-agents): other vendors' agents.
