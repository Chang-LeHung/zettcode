# Problems and questions

## It will not start

**`zettcode: Config key ... must be str` / `Unknown config keys ...`** — the
message names the key that is wrong. Typos are rejected rather than ignored, so
the fix is usually the spelling. `/guide/config` has the full list.

**`zettcode: No models configured`** — `~/.zettcode/config.toml` needs at least
one `[[models]]` table. Start from the example in
[Getting started](/guide/getting-started#name-a-model).

**`zettcode: no session <id> in <path>`** — `--resume` was given an id that this
workspace's store does not hold. Ids are per workspace: check `-w` points at the
same directory the session was created in, or run `zettcode` and use `/resume`
to pick from the list.

## It starts but nothing works

**The first request fails with a connection error.** The `base_url` is the
OpenAI-compatible *root*, usually ending in `/v1`; a URL pointing at a web page
or missing the version segment is the common mistake. Check that the endpoint
answers a plain chat-completions request with the same token.

**The model name is rejected.** Use the id the endpoint expects, not the name
you see in a UI — `display_model` is what the header shows, and it is free text.

**It is slow to show the first frame.** It should not be: settings and the
session are ready before the provider SDK is even imported, and the status line
says `ready`. If the window takes longer than a moment, the terminal itself is
usually the reason — a large scrollback or a remote connection. `zettcode
--dry-run` times the startup without taking the screen.

## The screen

**Colours are wrong, or text is invisible.** Run `/theme light` or `/theme
dark`. At startup ZettCode asks the terminal for its background colour; a
terminal that does not answer, a multiplexer in between, or `TERM` lying about
its colour depth can all mislead it. `/theme` overrides that for the session,
and `~/.zettcode/theme.toml` overrides it for good.

**The display is garbled after a while.** `Ctrl-L` repaints from scratch.
Resizing the window is handled, but a program that wrote to the terminal behind
ZettCode's back cannot be.

**Copying does not work in my terminal.** ZettCode copies the selection itself
when you release the drag, so the terminal's own selection is bypassed. If you
prefer the terminal's, hold its selection modifier (<kbd>Shift</kbd> or
<kbd>Option</kbd>) while dragging.

**A pasted image does nothing.** Image paste needs the desktop clipboard, so it
works on macOS and on Linux with `wl-paste` or `xclip` installed, and is not
available on Windows. A terminal that pastes an image *as text* (VS Code's, for
instance) is recognised anyway.

## Sessions

**I lost a conversation.** Everything is appended to
`~/.zettcode/sessions/<workspace key>/<session id>/data.jsonl` as it happens, so
it is still there: `/resume` lists what this workspace has, newest first. The
same folder's `metadata.jsonl` holds the titles.

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
tool output. `/compact` summarizes now instead of waiting for the trigger.

**The cache hit rate is low.** The provider caches a prefix, so anything that
changes early in the request breaks it — a different system prompt, a different
set of tools, a different model. Switching models mid-session, editing
`AGENTS.md`, or changing the skills on disk all reset it; a steady rate in the
seventies is normal for a session with tools.

**A command ran that I did not want.** It cannot have: `run_shell` always asks
unless you pressed `a`, which allows the rest of that run only. `p` remembers
one exact command for the session, and `Esc` refuses. Approval state is per run
and never persists to the next one.

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

## Leaving

**How do I exit?** `/quit`, or `Ctrl-D` on an empty composer. **Ctrl-C** stops
the running request, and on an empty request clears the draft — it does not
quit. On exit the shell prints the `zettcode --resume …` line for the session
you were in.
