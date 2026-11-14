# What it can do

Most of this guide is about one session in one terminal. ZettCode also does a few things a single-session terminal
agent does not. This page names each one, says what is different about it, and shows the commands that use it. The
details are on the page each section links to.

| Capability | In one line | Needs |
| --- | --- | --- |
| [JIT harness](#jit-harness) | The model writes a small Python tool, loads it and calls it in the same turn | `zettcode` (off until you turn it on) |
| [Code review](#code-review) | `/code-review` has a second agent read your uncommitted changes | `zettcode`, and a git checkout |
| [Background agents](#background-agents) | A session with nobody at the keyboard, started with `zettcode daemon spawn` | `zettcode` |
| [Messaging and `@`](#messaging-between-sessions) | Sessions on one machine send each other messages; `@name` points the model at one | `zettcode` |
| [Groups](#groups) | A named set of sessions; a message to the group reaches every connected member | `zettcode` |
| [The Graph page](#the-graph-page) | Sessions as nodes, groups as regions, messages as they travel, with replay | `zettcode gateway start` |
| [The web gateway](#the-web-gateway) | A page for daemons, sessions and groups, also on a phone and in a desktop window | `zettcode gateway start` |
| [Codex and Claude Code](#codex-and-claude-code) | Both run as members you can message and put in groups | `zettcode[code-agents]` and the Codex or Claude Code CLI |

Everything but the last row is in plain `zettcode`; `[all]` adds `/monitor`, `/recap`, the vendor models and the last
row. See [Getting started](/guide/getting-started#install).

## JIT harness

**What it is.** With the harness on, the model can create a small Python repository, write a tool into it, load it with
`repo_load` and call it in the same turn. The tool is plain Python under `~/.zettcode/harness/<workspace>/<session id>/`,
and every step shows as a row you can expand.

**Why it differs.** A fixed tool set can only do what its authors thought of. Here the model can write the one-off tool
a task needs, such as "list every `TODO` with its owner from `git blame`". The code runs in a child process, so a crash
or a hang stays out of your session. Below the `full` shell level it runs inside the boundary `safe` uses. At `full`
it has your own access. It is off unless you turn it on. `/harness gen` tells the model to keep its writes in the
harness folder and not to edit your project's files; that is an instruction to the model, not a sandbox.

**How to use it.**

```text
/harness gen find the TODO comments in this repository and group them by file
/harness reset
```

`/harness gen` turns the harness on for this run and asks the model to build one tool for the workspace.
`/harness reset` turns it off for this run and deletes nothing. The harness is on by default; to start every run with
it off:

```toml
# ~/.zettcode/config.toml
[harness]
jit = false
```

**Details.** [The JIT harness](/guide/harness).

## Code review

**What it is.** `/code-review` asks the model to review the uncommitted changes in the workspace. The model starts a
background session named `code-review` (or reuses the one already running for this workspace), sends it the request,
and goes round again after each fix until the reviewer has nothing left to change.

**Why it differs.** The review happens in a session of its own, so your conversation does not fill up with the diff, and
a reviewer that has seen the earlier rounds can say whether a fix worked. The reviewer is told to read and not change
files. That is an instruction, not a sandbox: it runs at your own shell level (or at `safe` when yours is `ask`), so at
`full` it could change things if it chose to.

**How to use it.**

```text
/code-review
/code-review the error handling in src/api.py
```

Under the `deny` shell level no reviewer is started; the model reads the files itself.

**Details.** [Code review](/guide/code-review).

## Background agents

**What it is.** A daemon is a session with nobody at the keyboard. It works in a workspace of its own, keeps running
when you close the terminal, and is reached by messages. You start, list, stop and delete daemons from the command line
or from the web gateway.

**Why it differs.** A terminal session lives in its terminal: close the window and it ends. A daemon keeps working after
you close the terminal, so a long job (going through a failing test suite, reviewing a diff) does not tie up your own
session. A daemon is an ordinary stored session, so after it stops you can open it with
`zettcode resume <id>`. `daemon stop` keeps its record, and `spawn --resume` starts it again on the same conversation.

::: warning A daemon asks nobody
Nobody is there to approve a command, so a daemon never asks. Its shell level is `full` by default: every command runs
with the access of the account that started it, with no sandbox. Pass `--permission safe` (commands in a sandbox) or
`--permission deny` (no shell) unless the workspace is one you would give a shell to.
:::

**How to use it.**

```bash
zettcode daemon spawn --name builder --title "tool builder" --permission safe
zettcode daemon list
zettcode daemon prompt <session-id> "Run the tests and tell me what fails."
zettcode daemon stop <session-id>
```

`spawn` prints the session id. `daemon list` shows each daemon's status, model, context use and shell level.

**Details.** [Background agents](/guide/daemons).

## Messaging between sessions

**What it is.** Every session registers with a small local broker (it listens on `127.0.0.1` and needs a token file in
`~/.zettcode/broker/`). Each session has a name, shown in its header. Type `@` in the composer to pick another session;
the model then sends the message with its `send_message` tool.

**Why it differs.** Sessions can hand each other work instead of you copying text between terminals. A message that
arrives is marked with who sent it, and the model is told it is a request from a colleague, not an instruction from you.
When the receiving session is busy, a message either steers the running request or waits as a follow-up. Sessions on
the same machine and user only: nothing goes over a network.

**How to use it.** With a daemon running, in a terminal session:

```text
❯ @tool-builder write a helper that lists TODO comments, then tell me its name
```

The name after `@` comes from the session's title, then its folder; the menu shows the real name. The send is a row in
the conversation (`Delivered to …`, `queued`, or why it was not sent).

**Details.** [Talking between sessions](/guide/messaging).

## Groups

**What it is.** A group is a named set of sessions, written `#name`. A message sent to a group goes to every other
member that is connected, and each is told which group it came from.

**Why it differs.** One message can reach a planner, a reviewer and a tester at once, and each can answer the whole group
or only the sender. A group is kept by the broker, so it survives a restart. A member that is offline misses the message,
though it stays in the history. Each message costs every member a turn, so tell agents to answer only when an answer is
needed.

**How to use it.** Ask a session's model to create one (it uses the `manage_group` tool), or press **New group** on the
gateway's Chats page. The limits are 64 sessions in a group, 20 groups for one session and 200 groups per machine.

**Details.** [Talking between sessions: group chats](/guide/messaging#group-chats).

## The Graph page

**What it is.** A page of the web gateway. Each session is a node, each group a shaded region, and each message travels
along a line from the sender to the recipient as it is sent. **Replay** redraws a past stretch of time from the stored
history, up to 20,000 messages.

**What it is for.** It does not change what the agents can do; it shows what they did. With several agents talking, it
answers who is talking to whom and where a conversation stalled. Replay only draws what happened; it sends nothing
again.

**How to use it.** Start the gateway and open **Graph** in its navigation:

```bash
zettcode gateway start
```

**Details.** [Talking between sessions: the graph](/guide/messaging#the-graph).

## The web gateway

**What it is.** `zettcode gateway` serves a web page for the daemons and sessions on the machine: the chats, a list of
daemons you can start, stop and restart, the groups, the Graph, the daemons' logs and the model configuration. The
page listens on `127.0.0.1:8765` by default.

**Why it differs.** The terminal stays where the code is and the page follows you, including to a phone. You can start a
daemon from a browser instead of a shell. It signs in with a token (`--token`), can hand out a second read-only token,
and exposes `/metrics` and an audit log.

**How to use it.**

```bash
zettcode gateway start        # detach, print the address
zettcode gateway stop
```

To reach it from a phone, listening beyond this machine needs a token; see [Web gateway](/guide/gateway#signing-in-and-who-may-use-it).
The page is plain HTTP, so put it behind TLS if it leaves a network you trust. The desktop (Electron) and Android
shells are windows on the same page; the macOS app is signed ad hoc and the Windows and Linux ones are not signed at
all. See [Desktop & phone apps](/guide/app).

**Details.** [Web gateway](/guide/gateway), [Desktop & phone apps](/guide/app).

## Codex and Claude Code

**What it is.** The `code-agents` plugin runs **Codex** and **Claude Code** as members of your group. Each is a
persistent command-line session whose id is kept in `~/.zettcode/code-agents/`, so every message continues the same
conversation.

**Why it differs.** You can put them in the same group as your own daemons and sessions, and address them with `@`. The
plugin only starts the command-line tool you already have; it needs the Codex or Claude Code CLI installed and signed in
for the user running the gateway.

::: warning Permission defaults to `full`
The plugin's default is `full`: the agent may do anything you may, because nobody is there to answer a prompt.
Starting the gateway with `--no-full` does not limit these agents. Set `"permission"` to `workspace` or `read` in
`~/.zettcode/code-agents/config.json` to narrow them.
:::

**How to use it.**

```bash
pip install "zettcode[code-agents]"     # or zettcode[all]
zettcode gateway restart
```

Open **New** in the gateway, choose the **External agent** tab, pick Codex or Claude Code, optionally name a group to
join, and press **Start external agent**.

**Details.** [Codex & Claude Code](/guide/code-agents).
