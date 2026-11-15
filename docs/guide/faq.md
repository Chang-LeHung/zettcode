# Problems and questions

Start here when something does not work. Each answer is one paragraph and a link; the page it links to carries the
detail.

## The install fails, or `zettcode` is not found

Keep the quotes: `uv tool install "zettcode[all]"` — `fish` and `zsh` read an unquoted `[all]` as a pattern. A
`command not found: zettcode` after a clean install means the tool's directory is not on your `PATH`; `uv tool install`
prints the line to add. If you upgraded from 0.3 and see `ModuleNotFoundError`, a package manager removed the old
distribution's files after writing the new ones, so install over it once:
`pip install --force-reinstall "zettcode[all]"`. See [Getting started](/guide/getting-started#install).

## It starts with no model, or the first request fails

`No models configured` means `~/.zettcode/config.toml` has no `[[models]]` table: the terminal still opens, the header
reads `no model`, and `/config` walks you through the first entry. A connection error usually means `base_url` is wrong
— it is the API root, not the chat page, so DeepSeek uses `https://api.deepseek.com` and some endpoints need `/v1`.
Check it with the [connection test](/guide/config#checking-the-connection), and see
[Getting started](/guide/getting-started#connect-a-model) for a working entry.

## `ctx` is high

Open `/context`: every percentage there is a share of the request, so the biggest row is what is filling it, usually
`Tool output`. Read a range of lines instead of a whole file, and turn off the MCP servers and skills you do not use.
See [The context window](/guide/context).

## I want to compact now

`/compact` summarizes the conversation immediately instead of waiting for the trigger, and keeps only the last turn
verbatim. It is not `/clear`: it changes what later requests carry, not what is on screen. See
[Compaction](/guide/context#compaction).

## I stopped a request by mistake

`Esc` or `Ctrl-C` stops the request and keeps what it had already done. `/continue` carries it on from where it stopped,
and a request that failed or hit the output limit resumes the same way. See [Commands](/guide/commands#continue).

## A new version is offered

Once a day ZettCode asks PyPI in the background, and a newer release shows as a panel with **Upgrade now**, **Skip this
version** and **Not now**; only a confirmed install is remembered, and the window keeps the code it started with, so
restart to use it. `[update] enabled = false` turns the check off, and `zettcode update` upgrades without waiting to be
asked. See [Optional features](/guide/config#optional-features).

## On Windows

Install and run it in Windows Terminal rather than the legacy console, which does not deliver the key events the screen
needs. The `safe` level does not sandbox on Windows — it runs only the commands it recognises as read-only — so leave
the level at `ask`, one keypress per command. Image paste is not available; give the model a path instead. See
[Approvals](/guide/interface#the-safe-sandbox).

## I lost a session

Nothing is lost: every session appends to `~/.zettcode/sessions/<workspace key>/<session id>/data.jsonl` as it happens.
`/resume` lists this workspace's sessions, newest first, and `--resume` only finds one when `-w` names the directory it
was created in. See [Sessions](/guide/sessions#where-they-live).

## The short ones

- **Colours are wrong.** `/theme light` or `/theme dark` fixes it for the session; `[ui] theme` in `config.toml` makes
  it stick. [Colours](/guide/config#colours).
- **The screen is garbled.** `Ctrl-L` repaints it. A program that wrote to the terminal behind ZettCode's back cannot
  be repaired. [The transcript](/guide/interface#the-transcript).
- **Copy does not work.** ZettCode copies the selection itself when you release the drag; hold <kbd>Shift</kbd> or
  <kbd>Option</kbd> to use the terminal's instead. Over `ssh`, see
  [Copying over `ssh`](/guide/interface#copying-over-ssh).
- **A skill, MCP server or plugin does nothing.** The failure is reported by name and the session keeps going; import a
  plugin in a plain Python shell to see its error, and read `~/.zettcode/log/tui.log` for a server's banner. See
  [Plugins](/guide/plugins#when-something-goes-wrong) and
  [Skills and MCP](/guide/skills-and-mcp#when-a-server-or-a-tool-goes-wrong).
- **I need to report a failure.** Attach `~/.zettcode/log/tui.log` for terminal output and
  `~/.zettcode/log/terminal.jsonl` for events; a failure there carries its traceback.
  `ZETTCODE_LOG_LEVEL=debug` adds the request and tool path. Read the file first: message bodies are not logged, but
  tracebacks are written verbatim.
- **I upgraded and it still says the old version.** `zettcode --version` and `which zettcode` name the copy you start;
  an editable checkout or a `PYTHONPATH` can be supplying the code, and ZettCode says so once instead of offering the
  same upgrade again.
- **The conversation is not what I sent.** Chips such as `@skill` and images are expanded for the request and kept as
  chips for you, which is why a resumed session shows the chip.
- **A session does not resume the same way.** Titles and totals come from the metadata index and the conversation from
  the JSONL tree; a last line cut off by a crash is ignored, and the rest still loads.
- **How do I exit?** `/quit`, or `Ctrl-D` on an empty composer. `Ctrl-C` stops a request instead of quitting.

## Next steps

- [Getting started](/guide/getting-started): install, add a model, start a task.
- [The interface](/guide/interface): what each row of the screen means.
- [Commands](/guide/commands): every slash command.
