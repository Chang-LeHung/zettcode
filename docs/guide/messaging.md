# Talking between sessions

Several ZettCode sessions can run on one machine at once — one fixing a parser, one writing its
docs, one reviewing a branch. They can see each other and pass messages: a session you name with `@` is a
reference your model can pass a message to with a tool.

## How it works

Every session registers, when it starts, with a small background process called the **broker**. The
first session to start one starts it; it keeps running while any session is connected, and quits about
thirty seconds after the last one leaves. It listens only on `127.0.0.1`, and only a process that can read
a file in `~/.zettcode/broker/` (which holds the token a connection must present) can talk to it. A session that cannot reach it works exactly as it did
before: nothing waits for it and nothing breaks.

Each session is listed under a **name** that you can type after `@`. It is made from the first of these that
exists:

1. the session's **title**: `Fix the parser` is `fix-the-parser`;
2. the **folder** it works in: a session with no title yet, in `~/work/zettdemos`, is `zettdemos`;
3. `session-` and the last six characters of its id, for a title and a folder with no letters in them.

Names are lower-case ASCII. If two sessions would share one — two untitled ones in the same folder do — the
later one keeps the name and adds the end of its id (`zettdemos-4a77c1`), which is unique and does not change. A
session's name changes when its title does — the title is written after the first reply — so look at the menu
rather than relying on a name you saw a minute ago.

**Your own session's name is in the header**, after the title (`◈ zettcode  Fix the parser · @fix-the-parser · ~/work`),
so you can tell somebody what to type to reach you.

## Writing to another session

Type `@` and the name of a session that is running. The menu lists the sessions as you type, each with
what it is about, whether it is working, and the folder it works in. What you type is matched against the name, the
title, the folder and the start of the id, names first, so `@parser` finds the session titled "Fix the parser".

```text
❯ @fix-the-parser can you check that the tokenizer still handles tabs?
```

A name after `@` is a reference like a file or a skill, so the draft still goes to this session's model. The model
reads `session "fix-the-parser"` in place of the `@`, is told which session that is and how to reach it, and calls
`send_message` itself. When your message begins with the name, as above, what follows it is what the model passes on;
when the name appears in a sentence, it decides whether your request is for that session. Either way the shell sends
nothing itself: your message shows as you typed it, and the send is the model's tool row, with who it went to and
how it ended (`Delivered to …`, `queued`, or why it was not sent). `queued` means that session was busy and will
start on it when its current request ends. The other session sees the message as coming from this session's agent,
because that is what sent it.

The tool sends text only, and refuses a message over 32,000 characters. A name nobody has, or a session that has
left, is ordinary text: nothing explains it to the model.

## Receiving a message

A message that arrives is treated like one you typed in that session, with two differences you can see.

- It is drawn like your own messages — the same `›` and the same text column — on a bluish
  slightly different background instead of yours (a lavender-grey in the dark theme, a pale sage in the light one),
  with a line above the text that says which session it came from and
  whether its agent or its reader wrote it. The colour of that line tells the three cases apart: mauve for another session's agent, yellow for its reader, green for you.

  ```text
  ← agent of session fix-the-parser
  › The tokenizer change is merged. Can you rerun the parser tests against main?
  ```

- The model is told where it came from. A message from another agent is a request from a colleague, not
  an instruction from you, and it is asked to weigh it against what you have asked and not to do anything
  destructive on its say-so alone.

Everything after that is an ordinary request: the wait row, the answer, the list of files it changed, the
title, the stored session. The message is saved with the session and shows the same way when you resume it.

- **When the session is idle**, the message starts a request at once. This costs tokens without you pressing
  Enter, which is the point of a message from another session; switch the feature off if you do not want it.
- **When it is busy**, what happens is up to the message. A **steer** message (the default) is handed to the
  request that is running, so it changes course now; a **follow-up** waits and starts when the request in flight
  ends, after any follow-ups you queued. A message that cannot be steered — a command or a side question is
  running rather than a request, the steering limit is reached, or it came from a one-to-one chat window, which is
  answered by the turn its message starts — waits like a follow-up, and the sender is told it is queued. At most 16
  can wait; the sender is told when it is full.

  A daemon never steers — it runs one turn at a time and answers `queued` — and the web gateway's chat
  answers `delivered`: it keeps the message for the conversation it shows instead of starting a turn.

The answer to a message is shown to *you*. The session that sent it sees nothing of it unless the model
sends a reply with its tool.

## What the model can do

These tools are added to the model's:

| Tool | What it does |
| --- | --- |
| `list_sessions` | Lists the other running sessions: the name to use, the id, what each is about, whether it is idle or working, and its directory. A `/btw` side question may use it. It also lists the group chats this session is in, which are the only ones it may write to. |
| `send_message` | Sends a message to a session, by id, name or title, and returns once that session has taken it. It does not wait for an answer: a reply arrives later as a message of its own. It takes a `mode`: `steer` (the default) hands the message to the request the other session is running, and `followup` waits until that request ends. A side question cannot use it. Give `group` instead of `to` to write to a group chat: every other member that is connected receives it. |
| `message_history` | Reads what this session and one other session (`session`), or a group (`group`), said before. The broker keeps it across restarts. You can read only your own conversations and the groups you are in. A `/btw` side question may use it. |
| `manage_group` | Creates a group chat, adds or removes members, leaves it, or deletes it. |

In the conversation a `send_message` call is a row of its own, in mauve, the colour of the header
of a message another session's agent sent to you. It shows who the message was for and the first lines of what was
said, then how it ended (`Delivered to …`, or why it was not). Click the row to see the whole message and the whole outcome.

Two agents that keep answering each other would run for ever, so a message carries a count of how many
sessions it has passed through, and the broker stops one that would be the seventh. A new message starts the count
over.

## From outside ZettCode

The broker is a small web server on `127.0.0.1`, so anything on your machine that can read the token can use it: a
script, a CI hook, another tool. The port and the token are in `~/.zettcode/broker/broker.json`.

```sh
PORT=$(python -c "import json,os;print(json.load(open(os.path.expanduser('~/.zettcode/broker/broker.json')))['port'])")
TOKEN=$(python -c "import json,os;print(json.load(open(os.path.expanduser('~/.zettcode/broker/broker.json')))['token'])")

# who is there
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:$PORT/sessions

# send a message to a session, as "ci"
curl -s -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"to": "fix-the-parser", "text": "the build is red", "from": {"name": "ci"}}' \
  http://127.0.0.1:$PORT/messages
```

The answer comes once the session has taken the message (or says why not). A `mode` of `followup` makes a busy
session wait for its running request instead of steering it; leave it out and the message steers, which is the
default, and an idle session starts on it either way. The session shows it as coming from an
**external source**, and tells its model that who sent it was not checked: the model weighs it like any outside
request, and does not treat it as the person typing. A message cannot say it came from a reader or from another
agent, whatever it claims.

A program that wants to be listed, and to be answered, registers like a session: it opens a WebSocket at `/inbox` with
the same token, says `{"op": "session", "session_id": "...", "title": "...", "kind": "external"}`, and is then in the
list for everyone to write to. The messages it is sent arrive on that connection, and it sends back with the `key` it
was given. The whole exchange is described at the top of `zettcode/src/zettcode/broker/protocol.py`.

## Managing the broker

Nothing has to be started by hand: the first session that needs the broker starts it, and the last one to leave lets
it exit about half a minute later. To start, stop, or restart it yourself — after an upgrade, or when one is stuck —
run one of these in a shell:

```sh
zettcode broker start     # start one if none is running, and print its pid and port
zettcode broker stop      # stop the broker this machine is running
zettcode broker restart   # stop it, then start a new one
```

Each answers plainly what it did: `start` says the broker was already running (with its pid and port) rather than
starting a second one; `stop` says nothing was running rather than failing. Only a process recognised as ZettCode's
own broker is ever ended (its command line must be `python -m zettcode.broker`), it is asked to stop first, and a
broker that does not let go of its lock is forced. Sessions connected to it notice and reconnect to the next one.

A new version can speak a newer protocol, and a session still running the old code then cannot reconnect. So when
`restart` finds background agents (daemons) running, it lists them and asks before it goes on. On yes it stops them,
restarts the broker, and starts each one again on its own stored session with the same model, effort, name and shell
level; nothing they wrote is lost. On no, or with no terminal to ask in, it changes nothing. `zettcode broker restart
--yes` skips the question. Terminal sessions you have open are not touched: close and reopen them to join the new broker.

**After an upgrade this happens by itself.** Every time `zettcode` starts it glances at the running broker's note (a few
bytes, no network). If that broker speaks an older protocol than the code you just started, a background process runs
`zettcode broker reload`, which replaces it; the start itself never waits for it. `reload` is careful where `restart`
asks: a broker that is current or newer, or not running, is left alone, and so is one with background agents on it,
because stopping them is for you to agree to — it prints that it left the broker alone and how to restart it
knowingly. The same broker is tried at most once in ten minutes. A session that connects replaces an older broker
the same way, and a session that loses its broker (it was replaced, restarted or crashed) reconnects to the next one
by itself, at once when the broker said it was leaving; a send that was in flight then fails with a reason saying it
may or may not have arrived. Only a session still running the *old* code cannot follow a new protocol, and says so;
close and reopen it.

## Limits and care

- Sessions on the same machine and the same user only. Nothing is sent over a network.
- A message is cleaned of escape sequences and control characters before it reaches a terminal.
- No more than 20 messages a minute from one session.
- A session that cannot reach the broker, or has none, has no names in the menu; `@name` is then an ordinary
  reference for the model.
- Another session's agent has its own permissions. A message does not give it more.

## Turning it off

```toml
[sessions]
enabled = false
```

With it off the session does not register, `@` offers no session names, and the model has neither tool.

::: details The broker's files
Everything lives in `~/.zettcode/broker/` (or in `$ZETTCODE_BROKER_DIR`): `broker.json` holds the port, the
protocol version and the token (readable by you only), `broker.lock` makes sure one broker runs, and `broker.log` records its
start-up and any trouble. Stop it with `kill $(python -c "import json,os;print(json.load(open(os.path.expanduser('~/.zettcode/broker/broker.json')))['pid'])")`;
the next session starts a new one. `ZETTCODE_BROKER_IDLE` sets, in seconds, how long it stays after the last session leaves.

After you upgrade ZettCode, a broker left running by an older version cannot talk to the new one. A new session
notices, ends that broker (only if it really is ZettCode's broker) and starts its own, within a second or two; the
sessions that were connected to it reconnect to the new one by themselves. Nothing is waited for and nothing needs doing.
:::


## Group chats

A group chat is a named set of sessions, written `#name`. A message sent to a group goes to every other member
that is connected, and each of them is told which group it came from, so its model can answer the whole group
(`send_message(group="name", ...)`) or only the sender. Only a member may write to a group, read its history, or change
who is in it, and `list_sessions` shows a session only the groups it is in. Groups are kept by the broker, so they
survive a restart; a member that is not connected misses the message (it is still in the history).

A group is made with the `manage_group` tool, or by anyone holding the broker's token with `POST /groups`
(`{"action": "create", "name": "review", "members": ["parser", "docs"]}`). A group with nobody left is deleted.

Limits: a group holds at most 64 sessions, one session may be in at most 20 groups, and a machine has at most 200
groups. A message that would go past one of them is refused with a reason that says which.

## Pictures

A one-to-one message from a reader's chat window (the gateway's) may carry up to four pictures to a session that runs
the text as its own prompt, which today is a daemon: `images` on `POST /messages`, each `{"media_type", "data"}` with the
file in base64 (PNG, JPEG, GIF or WebP, 4 MiB each and 8 MiB together; a file must be what it says it is). A message to
a group, one an agent sent, and one for any other session is refused, and a daemon whose model does not read pictures
refuses them at once, with its reason, before a turn starts. The broker never keeps a picture: the history shows
`[2 pictures]` and nothing else. Sending them over the broker's protocol needs version 9, so older sessions are
replaced the same way as for any change of protocol (`zettcode broker restart`).

## History

The broker writes every message it hands over to `~/.zettcode/broker/broker.db` (a SQLite file; the newest 320,000
are kept, about 60 MB when full, and never more than 512 MB however long the messages are), with the names the sender and recipient had at that time. `message_history` and `GET /history` read it.

This is a transcript of every message between sessions, text included, kept on disk in a directory only you can list.
To clear it, stop the broker (`zettcode broker stop`) and delete `broker.db`. A `broker.db` written by a newer ZettCode
is never touched by an older one: that broker then remembers nothing until it runs again (the history tool says "No
messages yet" and the graph starts empty), and says so in `broker.log`. Limits on who reads it protect a model from
its own mistakes, not from another program running as you: any process that can read the broker's note holds its token.
Each message a group receives costs every member a turn, so tell agents to answer only when an answer is needed.

## The graph

`zettcode gateway` has a **Graph** page: the sessions drawn round a circle, a line between any two that have
talked, a ring around the members of each group, and a packet that travels from the sender to each recipient
whenever a message passes. Hover a session, a line, a group or a packet for the details. **Replay** shows a past
stretch of time (the last 15 minutes up to everything stored) from the stored history, with play, speed, and a
timeline you can drag. Replaying only draws what happened: nothing is sent to any session again. A replay reads at
most 20,000 messages of the period you chose; when the period held more, the page says its first part is missing, and a
shorter period shows all of it.
