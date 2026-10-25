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
- **When it is busy**, the message waits and starts when the request in flight ends, after any follow-ups
  you queued. It never steers the request that is running — "change what you are doing" is yours to say.
  At most 16 can wait; the sender is told when it is full.

The answer to a message is shown to *you*. The session that sent it sees nothing of it unless the model
sends a reply with its tool.

## What the model can do

Two tools are added to the model's:

| Tool | What it does |
| --- | --- |
| `list_sessions` | Lists the other running sessions: the name to use, the id, what each is about, whether it is idle or working, and its directory. A `/btw` side question may use it. |
| `send_message` | Sends a message to a session, by id, name or title, and returns once that session has taken it. It does not wait for an answer: a reply arrives later as a message of its own. A side question cannot use it. |

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

The answer comes once the session has taken the message (or says why not). The session shows it as coming from an
**external source**, and tells its model that who sent it was not checked: the model weighs it like any outside
request, and does not treat it as the person typing. A message cannot say it came from a reader or from another
agent, whatever it claims.

A program that wants to be listed, and to be answered, registers like a session: it opens a WebSocket at `/inbox` with
the same token, says `{"op": "session", "session_id": "...", "title": "...", "kind": "external"}`, and is then in the
list for everyone to write to. The messages it is sent arrive on that connection, and it sends back with the `key` it
was given. The whole exchange is described at the top of `zettcode/src/zettcode/broker/protocol.py`.

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
