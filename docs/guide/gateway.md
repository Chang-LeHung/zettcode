# Web gateway

`zettcode gateway` serves a web page for the background agents on this machine. It is a page, not an
agent: a left rail with the chats, a list of daemons and sessions, and a conversation. It works on a
phone as well, which is the point — the terminal stays where the code is, and the page follows you.

```sh
zettcode gateway                    # serve here until Ctrl-C
zettcode gateway --port 9000        # the same, somewhere else
```

The page is served on `127.0.0.1:8765` by default. Start it once, then open the address it prints.

## Running it in the background

```sh
zettcode gateway start              # detach, return at once, keep it running
zettcode gateway stop               # stop the one that is running
zettcode gateway restart            # stop it and start again
```

`start` says where the page is and how to sign in, writes its output to `gateway.log` in the gateway's
folder (`~/.zettcode/gateway` by default, or `--directory`), and returns once the page answers.
`restart` with no flags keeps the settings the running gateway was started with — host, port, token,
roots — so restarting does not quietly change the address or lose the sign-in. Give a flag to change one
(`zettcode gateway restart --port 9000 --token new`).

Only a process recognised as the gateway is ever signalled: stopping checks the command line first, so a
stale record or a reused process id cannot end something else. A gateway that is not running is not an
error; `stop` says so and exits 0. The one exception is a process that exists but whose command line
cannot be read: `stop` keeps its record and exits 1 rather than guess, because that process may be the
gateway.

## Signing in and who may use it

- With no `--token` there is no sign-in, and the gateway only listens on this machine. The page prints
  the URL with nothing to type beyond it.
- With `--token` (or `$ZETTCODE_GATEWAY_TOKEN`) the page asks for that token once and keeps a cookie.
- Listening beyond this machine (`--host 0.0.0.0`) requires a token: without one anybody who can reach
  the port could run commands as you. The page is plain HTTP; put it behind TLS if it leaves the machine.
- `-r`/`--root` limits where a daemon may be started; by default any directory may be chosen.
  `--no-full` refuses to start daemons at the full shell level (no sandbox and no approval); `--full`
  allows it again after a recorded `--no-full`.

## What the page can do

The page lists the daemons and the other sessions this machine has. A daemon can be started and stopped
from it, and any of them can be talked to as a contact: what you type is sent as a message from the
gateway, and what the session says comes back into the same conversation. A message from the page waits
for the session's current request to end: the page does not show that request live, so it never changes
one you cannot watch. (The terminal asks whether to steer; the page simply waits.) The gateway is a session of
its own, registered with the broker like a terminal's, so the daemons see a person's messages — not an
agent's. Its name is `Web gateway`.

The gateway needs a model configured, because its session is a real one, though it never calls the
model itself. No model is the one reason `start` can fail with a message instead of a page; the log says so.
