# Talking between sessions

Several ZettCode sessions can run on one machine at once: one fixing a parser, one writing docs, one reviewing a
branch. They can find each other and pass messages through a small local broker. Nothing leaves the machine.

## Names

Each session registers under a name you can type after `@`. It comes from the session's title (`Fix the parser` →
`fix-the-parser`), else the folder it works in, else `session-` and the last six characters of its id. A later session
with the same name adds the end of its id, and a title written after the first reply renames it. Your own name is in
the header, after the title.

Type `@` to list the sessions: each shows what it is about, whether it is working, and its folder. The match tries
name, title, folder and the start of the id, names first.

## Send a message

```text
❯ @fix-the-parser can you check that the tokenizer still handles tabs?
```

`@name` is a reference, like a file or a skill: the draft goes to this session's model, which reads which session it
names and calls `send_message` itself. The shell sends nothing. The call is a row of its own that shows the recipient
and how it ended (`Delivered to …`, `queued`, or why not). The message is text only, at most 32,000 characters. A name
nobody has is ordinary text, and the model is told nothing about it.

## Receive a message

An arriving message is drawn like one you typed, in a different colour and with a line naming the session and whether
its agent or its reader wrote it. The model is told who sent it, and treats it as a request from a colleague: it weighs
it against what you have asked, and does not do anything destructive on its say-so alone.

- **Idle session:** the message starts a request at once. That costs tokens without you pressing Enter; switch the
  feature off if you do not want it.
- **Busy session:** a `steer` message (the default) is handed to the running request, so it changes course now; a
  `followup` waits for the request to end. A message that cannot steer — a command is running, the steering limit is
  reached — waits as a follow-up and the sender is told it is `queued`. At most 64 wait in the session; after that the
  broker holds the message (up to 500 per session) and delivers it when there is room.

The answer is shown to you. The sending session sees nothing of it unless its model sends a reply.

## Groups {#group-chats}

A group is a named set of sessions, written `#name`. A message to a group reaches every other connected member, and
each member is told which group it came from. Only a member can read the history or change the members. Create one
with the model's `manage_group` tool, or with **New group** on the gateway's Chats page.

Limits: a group holds 64 sessions, a session is in 20 groups, a machine has 200 groups. A message past one of them is
refused with the reason.

## What the model can do

| Tool | What it does |
| --- | --- |
| `list_sessions` | Lists the other running sessions, and the groups this session is in. |
| `send_message` | Sends text to a session or a group. Returns when it is taken, not when it is answered. `mode` is `steer` (default) or `followup`. |
| `message_history` | Reads earlier messages with one session, or in a group. Kept across restarts; only your own conversations and groups. |
| `manage_group` | Creates a group, adds or removes members, leaves it, deletes it. |

A side question (`/btw`) may use `list_sessions` and `message_history`, not `send_message`.

Two agents answering each other would run forever, so a message carries a count of how many sessions it has passed
through; the broker stops one that would be the seventh.

## From a script

The broker listens on `127.0.0.1`; the port and token are in `~/.zettcode/broker/broker.json`. Any process that can
read that file can list sessions and send a message:

```sh
PORT=$(python -c "import json,os;print(json.load(open(os.path.expanduser('~/.zettcode/broker/broker.json')))['port'])")
TOKEN=$(python -c "import json,os;print(json.load(open(os.path.expanduser('~/.zettcode/broker/broker.json')))['token'])")
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:$PORT/sessions
curl -s -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"to": "fix-the-parser", "text": "the build is red", "from": {"name": "ci"}}' \
  http://127.0.0.1:$PORT/messages
```

The receiver sees it as an external source and is told the sender was not checked. A Python program driving an agent
does not need the broker: `client.deliver("the build went red", mode="followup")` hands the session the message
directly. The broker protocol is described in `packages/zettcode-broker/src/zettcode/broker/protocol.py`.

## Limits and care

- Same machine and same user only.
- Escape sequences and control characters are cleaned before a message reaches a terminal.
- One session sends at most 20 messages a minute.
- Another session's agent keeps its own permissions; a message cannot raise them.
- Every message is kept in `~/.zettcode/broker/broker.db`. To clear it, stop the broker and delete the file.
- If the broker wedges, `zettcode broker restart` replaces it, and connected sessions reconnect by themselves.

```toml
# ~/.zettcode/config.toml
[sessions]
enabled = false
```

## The graph {#the-graph}

The gateway's **Graph** page pictures the traffic between sessions, and **Replay** redraws a past period from the
stored history. [Web gateway: the graph](/guide/gateway#the-graph) shows how to read it.

## Next steps

- [Web gateway](/guide/gateway): watch sessions and groups, and replay the graph.
- [Background agents](/guide/daemons): sessions with nobody at the keyboard.
- [Codex & Claude Code](/guide/code-agents): other agents in the same groups.
