# The web gateway

`zettcode gateway` is a web page for the background agents on one machine: a left rail (Chats, New, Config, Logs,
Settings), a list, and a conversation, drawn like a messenger so it works on a phone. It is not an agent. It is one
more session, with a person at it, that talks to daemons through the broker and reads what they did from the session
store.

```
browser (Vue + TS)  ⇄  zettcode.gateway.app  ⇄  service.Gateway  ⇄  backend.Backend  ⇄  zettcode.sdk
 clients/gateway        Starlette, cookie auth     threads, unread,    the one place the     Client, daemons,
                        one event WebSocket        sending, spawning   SDK is touched       sessions.history_of
```

## The command

`zettcode gateway` serves in this terminal. `zettcode gateway start|stop|restart` manage one in the background: a
started gateway is detached, writes its output to `gateway.log` in its folder, and returns once it is a session and
its port accepts connections. A serving gateway records its pid and the settings it was started with in `run.json`
once `backend.start` has succeeded (`runfile.py`), so a second gateway that lost the session cannot overwrite the
record of the one that kept it. The record is written inside startup: a folder it cannot write is a folder that could
not keep the session's own `host.json` either, so there is nothing to serve from it.

The page sends its messages as **follow-ups**, deliberately (`SdkBackend.send`): a person typing in a chat does not see
the session's live turn, so steering it from there would change a request they cannot watch. A session that answers
`steered` (a newer server, or a session whose other front end chose it) is drawn as a running turn, because that is
what it is.

`stop` reads that record and decides from the process's command line, four answers of which three act: a command line
that is this gateway (`python -m zettcode.gateway.cli`, or the `zettcode` console script with `gateway`) is signalled;
one that belongs to something else, or a pid that is gone, means the record is stale and is removed; a pid that exists
but whose command line cannot be read is neither — the record is kept and both `start` and `stop` exit 1, because that
process may be the gateway and neither ending it nor starting a second one is right. `processes.still_there` is what
tells the last case from "gone": on POSIX it probes with signal 0, and on Windows it asks the process table with
`OpenProcess`, because signal 0 there would terminate the process. The message names the record, so it can be removed
by hand once nothing is serving.
`restart` stops first and starts again with the flags it was given, keeping the recorded host, port and token where no
flag says otherwise, so restarting does not quietly change the address or lose the sign-in — a recorded token beats one
exported in the environment, because the page that is already open was given the recorded one. A background start
passes the token in `ZETTCODE_GATEWAY_TOKEN`, never on the child's command line, where the whole machine could read it.
`--no-full` is recorded too; `--full` undoes it on a restart.

## Files

```
zettcode/src/zettcode/gateway/
  chat.py      stored messages -> chat items (out / in / reply / tool / note); the request-for-an-answer footer
  backend.py   Backend (abstract) and SdkBackend: a Client that joined the broker, the SDK's daemon calls
  service.py   Gateway: threads, unread marks, send, spawn, stop, folder picker, events
  app.py       Starlette app: sign-in, JSON endpoints, /api/events, headers
  cli.py       zettcode gateway: serve, start, stop, restart
  runfile.py   the record a serving gateway leaves, and the log of a background one
  static/      the built page (not in git: `make gateway-ui` builds it, and the release workflow builds it before the wheel)
clients/gateway/   the page: src/{api,stores,lib,components}, tests with node:test
zettcode/src/zettcode/sdk/daemons.py   spawn_daemon / list_daemons / stop_daemon / daemon_log
zettcode/src/zettcode/processes.py     reading a process's command line, shared by the broker's and the gateway's stop
```

## Decisions

* **Words come from the store, control from the broker.** A thread shows the session's stored conversation, because
  a daemon does not always send what it concludes. The broker says whether a message was taken, who is there, and
  that something arrived. The gateway's own session keeps one id across restarts (`host.json`), so a daemon told to
  reply to it still can.
* **The gateway registers as a normal session** (not `kind=external`), so a daemon treats its messages as a person's.
  Every text to a daemon gets a footer asking it to answer with `send_message`; the page strips it when drawing.
* **Sent messages are drawn by the page until the store has them** (`lib/pending.ts`): a pending message carries a
  target count of identical stored messages, so two equal sends show twice and none shows doubled.
* **Security.** Loopback by default, a token (optional: with none the page opens straight in, only for a request whose `Host` is a loopback name, which stops DNS rebinding, and the command refuses to listen beyond loopback without one), an HttpOnly SameSite=Strict cookie, an `Origin` check on every write
  and on the socket (with no token it must be present too, so a bare `curl -X POST` is refused on an open gateway), a CSP that allows only the page's own files, roots for where agents may start (the whole filesystem unless `-r` narrows it), `full` shell
  unless the gateway was started with `--no-full`. Anyone signed in can run commands as the user; the page says so.
* **A turn as it happens.** The gateway `watch`es every session in the roster; the broker tells a session how many
  watch it (`watched`), and only while any do, `RunStream` (so the terminal and a daemon alike) publishes `begin`,
  `text`, `thinking`, `tool`, `tool_end`, `end` through the messenger, which batches text for 60ms. The broker passes
  them on without keeping anything and skips a watcher that is half a queue behind instead of dropping it. The gateway
  keeps the turn so far for a page that opens mid-turn (`live` in a thread), and on `end` reads the store first, so the
  stored message is there before the live one goes; a turn whose session vanished or fell silent is dropped, and so is
  every live turn when the broker connection comes back (pieces were missed). Text is sent in lines of at most 4000
  characters; the gateway `unwatch`es sessions that are no longer listed, because the broker caps what one connection
  watches. A direct turn that ended without an answer is sent back as a marked line (`sdk.types.DIRECT_*`) that the chat
  shows as a note until the person writes again.
* **Mobile.** One column under 720px: the list and the conversation slide over each other, the rail becomes a tab bar,
  safe-area insets and the visual viewport are respected, and the send key is Enter only with a fine pointer.

## Not yet

Editing models from the page, and Chinese strings (`i18n/zh.ts` is empty; English shows).
