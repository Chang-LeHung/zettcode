# Problems and questions

## It will not start

**`zettcode: Config key ... must be str` / `Unknown config keys ...`** — the
message names the key that is wrong. Typos are rejected rather than ignored, so
the fix is usually the spelling. [Configuration](/guide/config) has the full list.

**`zettcode: No models configured`** — this is what `zettcode ask` and `zettcode doctor` answer while
`~/.zettcode/config.toml` has no `[[models]]` table. The terminal does not stop for it: it opens, the
header reads `no model`, and `/config` walks you through the first entry — a provider, the model id and the
token — and writes it into that file, which it creates if this machine has never had one. A prompt typed
before then is refused with the same instruction, and the words stay in the box. The example in
[Getting started](/guide/getting-started#name-a-model) is there for editing the file by hand instead.

**`zettcode: no session <id> in <path>`** — `--resume` was given an id that this
workspace's store does not hold. Ids are per workspace: check `-w` points at the
same directory the session was created in, or run `zettcode` and use `/resume`
to pick from the list.

## It starts but nothing works

**The first request fails with a connection error.** The `base_url` is the
OpenAI-compatible API *root*, not the chat website or full completion route.
DeepSeek uses `https://api.deepseek.com`; other endpoints may require `/v1`.
Use the [connection test](/guide/config#checking-the-connection) with the same
model and key, and check API balance, permissions, and proxy settings.

**The model name is rejected.** Use the id the endpoint expects, not the name
you see in a UI — `display_model` is what the header shows, and it is free text.

**It is slow to show the first frame.** The model client is created lazily, but
local config, storage, and plugin loading still happen at startup. Try
`time zettcode --dry-run` on macOS/Linux, or
`Measure-Command { zettcode --dry-run }` in PowerShell, to measure the local
startup path. It paints a frame and exits; it does not test the API connection.
Compare with third-party plugins disabled before attributing the delay to the
model or terminal.

## The screen

**Colours are wrong, or text is invisible.** Run `/theme light` or `/theme
dark`. At startup ZettCode asks the terminal for its background colour; a
terminal that does not answer, a multiplexer in between, or `TERM` lying about
its colour depth can all mislead it. `/theme` overrides that for the session,
and `[ui] theme = "..."` in `config.toml` (or `~/.zettcode/theme.toml`) overrides it for good. `/theme ` with a
space opens a menu that previews every palette as you move through it.

**The display is garbled after a while.** `Ctrl-L` repaints from scratch.
Resizing the window is handled, but a program that wrote to the terminal behind
ZettCode's back cannot be.

**Copying does not work in my terminal.** ZettCode copies the selection itself
when you release the drag, so the terminal's own selection is bypassed. If you
prefer the terminal's, hold its selection modifier (<kbd>Shift</kbd> or
<kbd>Option</kbd>) while dragging.

**I use ZettCode over `ssh` and nothing reaches my clipboard.** Over `ssh` the copy is
sent to your *terminal*, which has to be willing to take it — see
[Copying over `ssh`](/guide/interface#copying-over-ssh) for the setting each terminal
needs, and for `ZETTCODE_CLIPBOARD` when the guess about where you are is wrong.

**A pasted image does nothing.** Image paste needs the desktop clipboard, so it
works on macOS and on Linux with `wl-paste` or `xclip` installed, and is not
available on Windows. A terminal that pastes an image *as text* (VS Code's, for
instance) is recognised anyway.

## Sessions

**I lost a conversation.** Everything is appended to
`~/.zettcode/sessions/<workspace key>/<session id>/data.jsonl` as it happens, so
it is still there: `/resume` lists what this workspace has, newest first. The
session folder's `metadata.json` holds its title.

**A session does not resume the same way.** Titles and token totals come from
the metadata index; the conversation comes from the JSONL tree. If the last line
of the file was cut off by a crash, that one line is ignored — the rest still
loads.

**The conversation is not what I sent.** The model sees what it saw; the screen
shows what you typed. `@skill` and image chips are expanded for the request and
kept as chips for you, which is why a resumed session shows the chip.

## Context and cost

**`ctx` is high and rising.** Open `/context`: the percentages are shares of
what the window is holding, so the biggest row is what is filling it — usually
tool output. `/compact` summarizes now instead of waiting for the trigger. See
[The context window](/guide/context).

**The cache hit rate is low.** The provider caches a prefix, so anything that
changes early in the request breaks it — a different system prompt, a different
set of tools, a different model. Model switches, compaction, and changed
instructions can lower it, and cache lifetime depends on the provider. There
is no universal expected percentage. See the
[calculation and examples](/guide/models#reading-the-status-line).

**A command ran that I did not want.** Check the level in the status line: `· full`
runs every command with your own access and `· safe` runs them in a sandbox that can write only the
workspace and `/tmp` (on Windows, or Linux without `bwrap`, it runs the ones it recognises as read-only), while
no marker means `ask`. `/permission ask` puts the question back, and
`/permission deny` stops shell commands altogether. A run started with
`--full` (or `--auto`, `--yolo`) begins at `full` for the same reason, without a line
in the conversation to say so. Earlier approval choices
matter too: `a` switched to `full`, `s` to `safe`, and `p` remembers an exact
command for the current process. Restarting clears all of it. The level applies
to the built-in shell tool, not to file-editing or MCP tools, and only `safe` sandboxes anything;
use version control and review the diff.

## Skills, MCP, and plugins

**My skill does not appear.** It needs a directory with a `SKILL.md` whose front
matter has `name` and `description`, under `~/.zettcode/skills/` or a configured
`[skills] roots`. Only the front matter is indexed, and a name declared twice
belongs to the earlier root.

**An MCP server does not start.** Its banner and errors go to
`~/.zettcode/log/tui.log`, because writing them on screen would corrupt the
frame. A server that fails is reported by name in the transcript; a URL that is
wrong or unreachable is the usual cause.

**A plugin was skipped.** Import it in a plain Python shell to see the error;
ZettCode reports the plugin name and keeps the session going. Two plugins cannot
share a name, and none can take a command name that already exists.

## New versions

**It offered me an upgrade.** Once a day ZettCode asks PyPI, in the background,
whether a newer release exists. No start waits for that request, and
`[update] enabled = false` turns it off entirely. When the answer names a newer
version, the next start shows a panel over the conversation:

- **Upgrade now** runs the upgrade for the install it came from — `uv tool upgrade zettcode`, or
  `pip install --upgrade zettcode` — in the background, **from PyPI's own index**
  (`https://pypi.org/simple`), because that is where the newest version was read from: a mirror
  configured on the machine can lag behind it, and the package manager would then answer "already
  satisfied" for a release that exists. The version is read from PyPI again at this moment, so what
  the install is measured against is what the index says now, not what the last check wrote down;
  the stored version is the fallback for a machine that cannot reach it.
  **The window takes no input while the upgrade runs** — the composer locks, the way it does for a
  session another process has open — since the code that would answer is being replaced under it.
  The window keeps the code it started with, so restart to use the new version.
  A package manager that exits cleanly has not necessarily installed anything (`uv tool
  upgrade` says "Nothing to upgrade" and succeeds; so does pip when its index has not listed
  the release yet), so ZettCode then reads the installed version back from a fresh process and
  tells you what it found: **installed**, **still the old version** (try again in a few minutes), or
  **could not be read back**. Only a confirmed install is written to `~/.zettcode/update.json`,
  so it is not offered again; one that did not take is offered again on the next start.
- **Skip this version** remembers it in `~/.zettcode/update.json`. That one is
  never offered again; a later release is.
- **Not now** (or `Esc`) writes nothing, so the next start asks again about the
  same version.

The offer comes from that file, never from the network, so a machine that is
offline simply hears nothing about versions.

**I don't want to wait to be offered.** Run `zettcode update` from a shell: it asks PyPI,
says so if you already have the newest release, and otherwise runs the same upgrade as
**Upgrade now** with the package manager's output on your terminal. It then reads the installed
version back from a fresh process and reports `updated 0.1.0 → 0.2.0` only when that is what
it found (otherwise it says the version is unchanged or could not be read back, and exits
with status 1 for a failure). The upgrade installs **from PyPI's own index** rather than a mirror the
machine is configured for, so a mirror that has not caught up cannot turn a newer release into
"already satisfied"; on a network where only a mirror is reachable, that run fails and the mirror's
copy is the thing to install by hand (`pip install --upgrade zettcode`, or `uv tool upgrade
zettcode`, without the index flag). Restart any open ZettCode to use the new version.

**I upgraded and it still says the old version.** Check which copy you are starting:
`zettcode --version` prints the version, and `which zettcode` the command. If ZettCode
confirmed the install but the program you start is older, something else is supplying the code —
an editable checkout, or a `PYTHONPATH` — and ZettCode says so once (naming the directory the
running code came from) instead of offering the same upgrade again. A different copy that was
never upgraded (for instance a `pip` install beside a `uv tool` one) is offered the upgrade
as usual, and the command it shows is the one for the copy that is running.

## Diagnostics

**Something failed and I need to report it.** The three long-running faces keep separate logs:

- terminal: `~/.zettcode/log/tui.log`
- broker: `~/.zettcode/broker/broker.log`
- gateway: `~/.zettcode/gateway/gateway.log`

The program appends one JSON object per key event and, for a failure, the exception type, message and traceback. Those JSON lines are mixed with each face's own text output (uvicorn's log, the broker's start/stop lines, and anything a child process wrote while the frame owned the screen), so parse them line by line. The paths above are defaults: `ZETTCODE_BROKER_DIR` and `ZETTCODE_GATEWAY_DIR` move the last two. A daemon's own log is `~/.zettcode/daemon/<workspace>/<session-id>/log`, and `zettcode daemon log <id>` prints it. The program does not add prompts, message bodies or credentials as fields, but an exception's message and traceback are written verbatim; review a log before attaching it.

## Leaving

**How do I exit?** `/quit`, or `Ctrl-D` on an empty composer. **Ctrl-C** stops
the running request, and on an empty request clears the draft — it does not
quit. On exit the shell prints the `zettcode resume …` line for the session
you were in.
