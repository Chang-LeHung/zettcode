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
- **Graph** draws sessions as nodes, groups as regions, and each message as a packet to its recipient. Hover for
  details; **Replay** redraws a past period from the stored history and sends nothing again. It reads up to 20,000
  messages of the period you choose.

## Monitor it

`GET /metrics` answers in the Prometheus text format for a dashboard or alert; the read-only token is enough.
The gateway also appends one JSON line to `audit.jsonl` in its folder for every sign-in, refused attempt and change:
the time, the token kind, the address, the route and the answer, never a token or message text. It rotates at 5 MB.

## Next steps

- [Talking between sessions](/guide/messaging): messages, groups and the broker.
- [Background agents](/guide/daemons): what the daemons are.
- [Desktop & phone apps](/guide/app): the gateway in a window or on a phone.
