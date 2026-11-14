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
- The [desktop and Android apps](app.md) load the gateway's own page at its own origin, so they need nothing here.
  A page of your own at another origin can be let in with `--client-origin https://client.example`; an origin is not a
  credential, so that needs a token too.

### A read-only token

`--read-token` (or `$ZETTCODE_GATEWAY_READ_TOKEN`) adds a second token that signs in **read-only**: whoever has it can
open the page, read every conversation, group and the graph, and watch live, but cannot change anything. Every change
is refused with `read_only` — sending, creating or deleting a group, starting, stopping or deleting a daemon, editing
models or agents — and the page hides those controls and says so. A reader may still mark a thread as seen and sign
out, and cannot use the folder picker, since it lists directories on the machine and belongs to starting a daemon.

Give it to someone who should watch the work, not steer it. It needs the main token (without one there is nobody to be
read-only next to) and must differ from it; either mistake stops the gateway from starting. Prefer the environment
variable: an argument is visible to every user of the machine in `ps`. A restart keeps it like the main token, and
changing a token ends every sign-in made with the old one.

### Metrics

`GET /metrics` answers in the text format Prometheus reads, for a dashboard or an alert. It needs a sign-in like
every other route, so a scraper sends the token as a bearer (`Authorization: Bearer <token>`); the read-only token is
enough, which is the one to give a monitoring system.

```yaml
scrape_configs:
  - job_name: zettcode-gateway
    metrics_path: /metrics
    authorization: { credentials: "<the read-only token>" }
    static_configs: [{ targets: ["gateway.example:8765"] }]
```

It reports the gateway's version and uptime; API requests (including the scrape itself, so its own route grows at your
scrape interval) by route, method and status class (`2xx`, `4xx`, `5xx`)
with a latency histogram per route; sign-in attempts by outcome (`read`, `write`, `failed`, `locked`); the event
sockets open now and accepted since the start; and, read at the moment of the scrape, how many sessions the gateway
lists, how many are online and working, and whether the broker is reachable. Counters live in memory and start again
at zero when the gateway restarts, which a scraper reads as a reset. Labels are only names the gateway chose (a
route's name, a status class), never a path or a value a client sent, so a client cannot grow the table by asking for
strange addresses. It carries no tokens, no message text and no session names.

### The audit log

The gateway appends one JSON line to `audit.jsonl` in its folder (`~/.zettcode/gateway` by default) for every
sign-in, sign-out and refused or failed attempt, every connection of the live event socket, and every change made
through it, with the time, whether it was the read or the write token, the address it came from, the route and the
answer. Plain reads are not logged. It records **that** something happened, never what: no token, no cookie, and no
message text. A change that answered with a server error carries `"outcome": "unknown"`, because the gateway cannot
tell whether it took effect; do not read a 500 as "nothing happened". The file is readable by its owner only and moves
to `audit.jsonl.1` once it passes 5 MB, so it holds the most recent stretch, not all of history. A refused socket is
logged at most once a minute per address, so a client reconnecting in a loop cannot push the sign-ins out of it. If the
file cannot be written the gateway keeps answering and says so once in its log.

## What the page can do

The page lists the daemons and the other sessions this machine has: the ones that are online first, then the ones that
are not, each group with the latest activity first. Group chats are listed above them, as in a messenger: open one to
read what was said in it, see its members and who is online, and write to it (writing adds the gateway to the group
if it is not in it). A daemon can be started and stopped from it — a daemon that is working asks you to confirm
before it is stopped — and a stopped one stays in the list, offline, until you delete it, which removes it and its
conversation for good. A stopped daemon has a **Restart it** button under its conversation (and in the chat's `⋯`
menu, and beside it in a group's member list): one press starts it again on the same conversation, with the folder,
model, reasoning level, shell level and label it had. **Change settings** (or `⋯` → *Change settings and restart*)
opens the New form filled in from it instead. A daemon stopped before anyone wrote to it has no conversation to
continue, so it can only be deleted and started anew; one that was set to the full shell level needs the gateway to
have allowed that when it started, like any new daemon. Any of them can be talked to as a contact: what you type is sent as a message from the
gateway, and what the session says comes back into the same conversation. A message from the page waits
for the session's current request to end: the page does not show that request live, so it never changes
one you cannot watch. (The terminal asks whether to steer; the page simply waits.) The gateway is a session of
its own, registered with the broker like a terminal's, so the daemons see a person's messages — not an
agent's. Its name is `Web gateway`.

**Working with messages.** Hover a message and press its `⋯` button (right-click it, or long-press on a phone) for
**Copy text** and **Reply**; the same menu is on messages in a group. **Reply** puts a bar above the input showing who
you are answering and a line of what they said; the `×` on it, Escape, or Backspace in an empty input drops it. When you
send, the message goes out with that text as a quote followed by yours, as ordinary markdown, so the agent reads it too. In a group the quote names who
said it; the name is cleaned of markup first, because a title is whatever its owner chose. Click a quote inside a
message (or focus it with Tab and press Enter) to jump to the message it came from: it is found by its words among
the messages loaded on the page, as whole words, so two messages that said the same thing are told apart only by being
nearer, a quote of only a couple of letters is too small to point at anything, and one that has scrolled out of what is
loaded (use **Show earlier messages**) or was never said here answers "The quoted message is not on this page."
**Ctrl/Cmd+F** searches the conversation, and typing `@` in a group lists the members you can address; an `@member` in a message is drawn in colour (yours, if you have a handle in the group, with a tint behind it). Backspace right after an `@member` you picked, or after a quote typed into the input, erases the whole thing at once. A group shows
a divider where the day changes (Today, Yesterday, the weekday, then the date). Scrolled up, a round button takes you
back to the newest message, with a count of what arrived meanwhile. A single conversation's history carries no times,
so it has no day dividers.

**Pictures.** A chat with a daemon has an attach button, and a picture can also be pasted or dropped on the
composer: up to four per message, 4 MiB each and 8 MiB together. A large picture is shrunk in the browser to what a
model reads anyway (1568 pixels on its longest side); a photo is always drawn again, which also drops what its file
says about where it was taken, and a small PNG, GIF or WebP goes as it is. The button is
off when the daemon's model does not read pictures, and for a session that is not a daemon or does not take a chat's
text as its own prompt, because a picture has nowhere to go there. The broker passes the pictures on and keeps none:
what it remembers of such a message is only that it had pictures. They are in the daemon's own conversation, which is
where the page shows them from.

The **Config → Models** page adds, edits and removes the models in `~/.zettcode/config.toml`, the same way
[`/config`](/guide/config#adding-models-with-config) does in a terminal: the rest of the file and its comments stay as
they are, a model the file would refuse is refused with the file's own reason, and the last model cannot be removed.
The API key is write-only: the page never shows a saved one, and leaving the box empty keeps it. A change reaches
the daemons you start afterwards; one that is already running keeps the model it started with. Anyone who can sign
in to the gateway can change this file, so keep the token private (see [Signing in](#signing-in-and-who-may-use-it)).
Edits made through the gateway are applied one at a time, but one made in a terminal's `/config` at the same moment
is not seen by it: the later write wins, so avoid editing from both at once.

The **Logs** page reads a daemon's own log as a list: when, which tool and what it was for, and each turn marked
where it starts and ends. It can be narrowed to tools or to problems, and searched.

The gateway needs a model configured, because its session is a real one, though it never calls the
model itself. No model is the one reason `start` can fail with a message instead of a page; the log says so.
