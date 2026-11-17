# Web gateway

`zettcode gateway` serves a page for the daemons, sessions and groups on this machine. It is a page, not an agent:
the terminal stays where the code is, and the page follows you to a phone.

## Run it

```sh
zettcode gateway                 # serve in the foreground until Ctrl-C
zettcode gateway start           # detach, print the address
zettcode gateway stop            # stop the one that is running
zettcode gateway restart         # stop it and start again
zettcode restart all             # the broker and the gateway, in the order that works (also: start, stop, broker, gateway)
```

It listens on `127.0.0.1:8765` by default; `--port` and `--host` change that. `start` writes its output to
`gateway.log` under `~/.zettcode/gateway` (or `--directory`) and returns once the page answers. `restart` keeps the
settings the running gateway had unless you pass a flag.

## Sign in {#signing-in-and-who-may-use-it}

| Setting | Effect |
| --- | --- |
| no `--token` | No sign-in, and the page listens on this machine only. |
| `--token`, `$ZETTCODE_GATEWAY_TOKEN` | Ask for that token once and keep a cookie. |
| `--host 0.0.0.0` | Requires a token. The page is plain HTTP: put it behind TLS. |
| `--read-token` | A second token that can read everything and change nothing. |
| `-r`, `--root` | Limits where a daemon may be started. |
| `--no-full` | Refuses daemons at the `full` shell level. |

Give the read-only token to someone who should watch the work, not steer it. The desktop and Android apps load this
page at its own origin, so they need no extra setting.

## What the page does

- **Chats** lists the daemons and sessions, online first, and the group chats above them. Open one to read it, see who
  is online, and write. A message from the page waits for the session's current request to end; it does not steer.
- **New** starts a daemon, or Codex or Claude Code when `zettcode[code-agents]` is installed. A stopped daemon can be
  restarted on the same conversation with the folder, model, level and label it had, or changed and started again.
- **Pictures** can be attached to a chat with a daemon: up to four per message, 4 MiB each and 8 MiB together, if the
  daemon's model reads images. The broker keeps none; its history says only that the message had pictures.
- **Config → Models** adds, edits and removes the models in `~/.zettcode/config.toml`, like `/config`. The API key is
  write-only: the page never shows a saved one.
- **Logs** reads a daemon's log as a list of turns and tools, with filters for tools and problems.
- **Graph** draws sessions as nodes, groups as regions, and each message as a packet to its recipients. See
  [the graph](#the-graph).
- **Dashboard** shows what the sessions have spent, read back from their stored conversations: requests, input and output
  tokens, and the cache hit rate (the share of the input the provider served from its cache; higher is cheaper and
  faster). Overview has a total and a card per group; Daemons has a card per daemon with its context fill. A group's chat
  shows the same totals under its header, and when members are stopped daemons it offers to restart them there.

## The graph

![The Graph page: one group of three sessions at the top, another of two at the bottom, four sessions outside both, and packets flying between them](/demo/graph.gif)

A group's members stand inside its outline, and its `#name` pill sits on the outside of that outline; a session in no
group stands alone on the ring.

Hover a node for its title, workspace, counts and groups, an edge for the messages the two sessions exchanged, or a
packet for the message it carries. Tab reaches the nodes too, and shows the same card. A group's card lists its
members.

**Live messages** beside the drawing lists the same traffic; select a message to play it again.

**Replay** redraws a period you pick from stored traffic and sends nothing again. It skips the quiet stretches unless
you turn that off, and **Back to live** returns to the running graph. A window holding more than 20,000 messages keeps
its newest part and says so.

## Monitor it

`GET /metrics` answers in the Prometheus text format for a dashboard or alert; the read-only token is enough.
The gateway also appends one JSON line to `audit.jsonl` in its folder for every sign-in, refused attempt and change:
the time, the token kind, the address, the route and the answer, never a token or message text. It rotates at 5 MB.

## Next steps

- [Talking between sessions](/guide/messaging): messages, groups and the broker.
- [Background agents](/guide/daemons): what the daemons are.
- [Desktop & phone apps](/guide/app): the gateway in a window or on a phone.
