# What it can do

Most of this guide is about one session in one terminal. This page names the eight things it does beyond that, each
with the command that starts it.

| Capability | In one line | Needs |
| --- | --- | --- |
| [JIT harness](#jit-harness) | The model writes, loads and calls a Python tool in one turn | `zettcode` |
| [Code review](#code-review) | A second agent reads your uncommitted changes | `zettcode`, a git checkout |
| [Background agents](#background-agents) | A session with nobody at the keyboard | `zettcode` |
| [Messaging and `@`](#messaging-between-sessions) | Sessions message each other; `@name` picks one | `zettcode` |
| [Groups](#groups) | A named set of sessions; one message reaches all | `zettcode` |
| [The Graph page](#the-graph-page) | Sessions as nodes, groups as regions, with replay | `zettcode gateway start` |
| [The web gateway](#the-web-gateway) | A page for daemons, sessions and groups, also on a phone | `zettcode gateway start` |
| [Codex and Claude Code](#codex-and-claude-code) | Both run as members you can message and put in a group | `zettcode[code-agents]` and that CLI |

Every row but the last is in plain `zettcode`; `[all]` adds `/monitor`, `/recap`, the vendor models and the last row.
See [Getting started](/guide/getting-started#install).

## JIT harness

The model writes a small Python tool for the task, loads it with `repo_load`, and calls it in the same turn. Use it
when a task needs a tool of its own, such as listing every `TODO` with its author from `git blame`.

```text
/harness gen find the TODO comments in this repository and group them by file
/harness reset
```

**Details.** [The JIT harness](/guide/harness).

## Code review

`/code-review` asks a second agent to read your uncommitted changes, in a session of its own, and goes round again
after each fix. Use it before you commit.

```text
/code-review
/code-review the error handling in src/api.py
```

Under the `deny` shell level no reviewer starts; the model reads the files itself.

**Details.** [Code review](/guide/code-review).

## Background agents

A daemon is a session with nobody at the keyboard: it keeps running after you close the terminal, and you reach it by
messages. Use it for a long job you do not want to sit through.

```bash
zettcode daemon spawn --name builder --title "tool builder" --permission safe
zettcode daemon list
zettcode daemon prompt <session-id> "Run the tests and tell me what fails."
zettcode daemon stop <session-id>
```

`spawn` prints the session id. Nobody approves a daemon's commands, so pass `--permission safe` or `deny`.

**Details.** [Background agents](/guide/daemons).

## Messaging between sessions

Every session registers with a local broker, so one session can send another a message. Type `@` to pick a session,
and the model sends the request.

```text
❯ @tool-builder write a helper that lists TODO comments, then tell me its name
```

The arrival is marked with who sent it. Sessions on one machine only.

**Details.** [Talking between sessions](/guide/messaging).

## Groups

A group is a named set of sessions, written `#name`; a message to it reaches every connected member. Use one when a
planner, a reviewer and a tester must hear the same thing. Ask a session's model to create one (it uses
`manage_group`), or press **New group** on the gateway's Chats page.

**Details.** [Talking between sessions: group chats](/guide/messaging#group-chats).

## The Graph page

A page of the web gateway: sessions as nodes, groups as regions, each message a packet to its recipients. Use it when
several agents talk and you want to know who is talking to whom. **Replay** redraws a past period and sends nothing
again.

```bash
zettcode gateway start
```

Open **Graph**.

**Details.** [The graph on the web gateway page](/guide/gateway#the-graph).

## The web gateway

`zettcode gateway` serves a page for the daemons, sessions and groups on this machine, on `127.0.0.1:8765`. Use it to
start a daemon from a browser, or to follow the work from a phone.

```bash
zettcode gateway start        # detach, print the address
zettcode gateway stop
```

With `--token` the page asks for it once and keeps a cookie; without one it listens on this machine only. It is plain
HTTP: put it behind TLS if it leaves a network you trust.

**Details.** [Web gateway](/guide/gateway), [Desktop & phone apps](/guide/app).

## Codex and Claude Code

The `code-agents` plugin runs **Codex** and **Claude Code** as agents you can address with `@`, each keeping one
persistent command-line session. Use it to put another vendor's agent beside your own.

```bash
pip install "zettcode[code-agents]"     # or zettcode[all]
zettcode gateway restart
```

Then open **New**, choose **External agent**, and press **Start external agent**. These agents run at `full` by
default; set `"permission"` to `workspace` or `read` in `~/.zettcode/code-agents/config.json` to narrow them.

**Details.** [Codex & Claude Code](/guide/code-agents).
