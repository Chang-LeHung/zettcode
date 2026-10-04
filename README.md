# ZettCode

ZettCode is a focused terminal coding agent built on `zett-agent`. Its TUI owns
raw terminal input, component layout, mouse interaction, and cell-level
differential rendering directly; it does not use prompt-toolkit or another TUI
framework.

The agent runtime is published separately as
[`zett-agent`](https://github.com/Chang-LeHung/zett-agent); this repository owns
only the terminal client.

## Install

ZettCode needs Python 3.14 or newer and is published on PyPI as `zettcode`:

```bash
uv tool install zettcode
# or
pip install zettcode
```

## Configure

ZettCode reads `~/.zettcode/config.toml` (override the path with
`ZETTCODE_CONFIG`). The file lists available models; the command line just
takes a workspace:

```bash
zettcode /path/to/project     # the workspace defaults to the current directory
```

```toml
# ~/.zettcode/config.toml
[[models]]
model = "gpt-4o"                       # model id sent to the endpoint
display_model = "GPT-4o"               # optional; shown in the header
token = "sk-..."                       # or set OPENAI_API_KEY
base_url = "http://tds.com:8787"       # OpenAI-compatible API root
responses_api = false
multimodal = true                      # accepts images as well as text

[[models]]
model = "deepseek-chat"
display_model = "DeepSeek Chat"
token = "sk-..."
base_url = "https://api.deepseek.com/v1"
```

Several models can be configured. The first entry is active at startup.
`/model` opens a picker panel over the conversation: `Up` / `Down` navigate
its scrolling list, `Enter` selects for future requests, and `Esc` closes the
panel and returns to the composer. Switching models adds a centered
`Model changed from … to …` line between horizontal rules in the transcript.
`/model GPT-4o` still switches directly by display name or model id.
`multimodal` records whether a model accepts images; it does not itself add
image input to the composer. Unknown keys and wrong types are reported, not
ignored.

Sessions live in `~/.zettcode/sessions/<base64 workspace path>/`, one append-only
JSONL file per session: every record carries a parent id, so a session is a tree,
and a compaction adds a summary node the active context is cut at. Each workspace
folder also holds `metadata.jsonl`, a small append-only log of titles and activity
times that is folded on read, so listing sessions never parses a conversation.
After the first reply the agent names the session with one small model call and
appends a title line. `/title <name>` names it by hand instead — before the first
message if you like — and that name wins: the background call never renames a
session that already has a title, and `/title` on its own reports the current
one. `/sessions` opens a picker panel listing recent sessions with
their title and how long ago they last changed; `Enter` resumes the highlighted
one, replacing the visible transcript with that session's active branch.
`/use <id>` and `/sessions <id>` also restore the selected conversation directly;
`/new` clears the visible conversation. The status line names the active session
once it has a title, in place of its short id. Sessions are not selected in the
config file.

The same line carries the session's token use: `↑22.0k ↓600 · 77% cached ·
100 tok/s` reads as cumulative input, cumulative output, the share of input the
provider served from cache, and generated tokens per second of model time. The
numbers come from a usage extension that accumulates the provider's own counters
and publishes them as a custom event after every model call, so the shell
mirrors them without polling; resuming a session seeds the totals from the
usage stored on its branch. The rate is a session average, not an instant
reading.

## Approvals

`run_shell` asks for confirmation before it executes anything. The prompt offers
`y` (run once), `a` (approve every later command this run), `p` (remember this
exact command, when the runtime can), and `Esc` to abort.

The agent's plan, when it publishes one, appears above the composer. Set
`ZETTCODE_REDUCED_MOTION` to suppress decorative animation.

## Colours

Everything is drawn from theme tokens, so a palette can be overridden without
touching code. `zettcode` reads `~/.zettcode/theme.toml` when it exists:

```toml
base = "dark"                 # dark | light

[ui]
accent = "#a7c080"
accent_bright = "#83c092"

[tools]                       # every role ships the same violet
read = "#b8a6e0"
shell = "#b8a6e0"

[code]
keyword = "#e58fa8"
string = "#9bddad"
comment = "#6d7a70"
number = "#d8b46a"
function = "#7fb7d8"
builtin = "#b8a6e0"
inline = "#9bddad"
```

At startup the shell asks the terminal for its background colour (a single
OSC 11 query, answered before anything else reads the keyboard) and picks `dark`
or `light` to match, so it follows whatever profile the window was opened with.
`~/.zettcode/theme.toml` turns that off: a palette file is a choice, so it is
used as written, and `/theme` overrides either way for the rest of the run.

Unknown keys and malformed colours are reported instead of silently ignored.
Tool rows are painted by what the tool did, but every role ships the same
violet — the colour the code palette already uses for ``print`` and
``__main__`` — so the look stays uniform until you decide which actions deserve
their own hue for your eyes. The `[tools]` table above is where that happens — give
`shell` a blue, keep `read` green — and a failed row is red whatever it ran.
An unrecognised tool, such as one from an MCP server, falls back to the
generic accent.

`/theme` opens a picker over the conversation; `/theme dark|light` still switches the
base palette in one step. The built-in
palettes take their accents from Everforest, so reasoning rows use the aqua
token while tool rows keep the green one and timings stay grey, instead of one
green for every row.

From a source checkout, run it through `uv`:

```bash
uv sync
uv run zettcode /path/to/project
```

## Keys

- `Enter`: send
- `Alt-Enter` / `Shift-Enter`: insert a newline
- `Ctrl-C`: stop the active request, or clear the input
- `Ctrl-D`: delete the next character; exit when the input is empty and the agent is idle
- `Ctrl-A` / `Ctrl-E`, `Home` / `End`: move to the start or end of the current line
- `Ctrl-B` / `Ctrl-F`, `Left` / `Right`: move by one character
- `Alt-B` / `Alt-F`, `Ctrl-Left` / `Ctrl-Right`: move by one word
- `Ctrl-Home` / `Ctrl-End`, `Alt-<` / `Alt->`: move to the start or end of the whole input
- `Ctrl-U` / `Ctrl-K`: delete to the start or end of the current line
- `Ctrl-W` / `Alt-Backspace`, `Alt-D`: delete the previous or next word
- `Ctrl-Y`: paste the last text removed with a line or word deletion
- `Ctrl-Z` / `Ctrl-_`: undo the latest input edit
- `Up` / `Down`: move between input lines, then browse submitted input history
- `Ctrl-P` / `Ctrl-N`: browse submitted input history directly
- `Ctrl-R`: search backward through submitted input history
- `Ctrl-L`: redraw the terminal
- `Ctrl-T`: expand or collapse the latest thinking block
- `Page Up` / `Page Down`: scroll history while keeping the composer focused
- `Esc` or the `↓ back to bottom` badge: jump to the newest line once scrolled up
- Mouse wheel: scroll history
- Click a Thinking or Tool row to expand or collapse it
- Drag in the transcript to select text; the selection is copied on release
- Double-click a transcript row to select the whole line
- `Shift`-click to extend the existing selection
- `Ctrl-C` copies the current selection and clears it
- Type `/` to open the command menu: `Up` / `Down` choose a command,
  `Enter` or `Tab` fills it in, and `Esc` closes the menu
- `Tab` / `Shift-Tab`: complete slash commands without the menu

Pointer-leave collapse of thinking and user-editable keybindings are not ported
yet; see `docs/tui.md`.

Thinking is collapsed by default. Tool calls keep their output and completion
status visible in the transcript, and completed tool rows show a five-row
preview until expanded. Expanded output is bounded so a large command result
cannot take over the terminal or exhaust renderer memory.

Every kind of agent output goes through a chain of render handlers before it is
shown. Tool rows read like a log rather than a payload dump — `Read src/app.py`,
`Ran pwd && ls -la`, `Edited app.py (2 edits)`, `Deleted notes.md`,
`Listed **/*.py`, `Searched TODO in src` — and a tool no handler knows still
degrades to `name key=value`, never JSON. A read row also names the scanner for
the file's extension, so the body is highlighted as the language it is. The
streamed text kinds go through the same chain: reasoning loses the
`<thinking>`-style wrappers a provider adds, and an answer loses the
`Assistant:` preamble a local model sometimes repeats, when the fragment that
opens the message carries one.

Pressing Enter puts a live row in the transcript straight away, so a slow model
is never mistaken for a frozen one. The row reads `Processing` and carries the
elapsed time in tenths, and is replaced by the real answer, reasoning, or tool
call as soon as one arrives. A request waits more than once: every tool batch is
followed by another model call, and `Processing` comes back below the rows it
belongs to until that call answers. Rows that are still running show the same
elapsed timer, and when the
turn ends the transcript closes with a muted summary of the wall time it took:
`Processed 51s · 09:41`, `Processed 22m 30s · 14:05`, or
`Processed 2h 5m 7s · 18:30`.

Assistant text renders common terminal-friendly Markdown: bold and emphasis,
strikethrough,
headings, inline and fenced code, links, quotes, bullet and numbered lists —
inset one level from the prose and wrapped under their own text — and GFM-style
tables. Code is highlighted by colour only, never by a background
block, and a fence draws only its code: the language label picks the scanner and
is never printed. The scanners cover Python, shell, JavaScript/TypeScript, Rust,
Go, Java, C/C++/C#, Ruby, PHP, SQL, Lua, Haskell, Swift, Kotlin, JSON,
YAML/TOML/INI, HTML/CSS, and LaTeX, with a generic fallback for anything else.
Tables have no outer frame but a rule closes the header and every row, drawn
per column so the gaps between columns stay visible; they keep left, center, and
right alignment, account for wide CJK characters, and wrap a cell that does not
fit instead of cutting its text.

The dark palette does not paint a page at all: it leaves those cells to the
terminal's own background, so the shell blends into whatever profile you run,
and only the surfaces it means to raise — the composer band, a user message, the
plan box — carry a colour. The light palette paints its own page, because a light
theme on a dark terminal has to. `[ui] background = "#232a2e"` in a theme file
makes the dark palette paint one too.

The terminal's window or tab name follows the session: it is the session title
once there is one, and `zettcode · <workspace>` before that. It is released when
the shell exits, so a prompt that sets its own title takes over again. VS Code
only lends the tab name to processes it recognises, so add `${sequence}` to
`terminal.integrated.tabs.title` there; iTerm2 needs no setting.

Use `/help` inside the application to see session commands; `/new`, `/sessions`,
`/use`, `/title`, `/model`, `/effort`, `/theme`, `/context`, `/clear`, and `/quit` are
available.
The composer command menu identifies each command as `app` or `agent`, shows
its description, and scrolls when there are more matches than visible rows.

`/effort` sets how much the model reasons before it answers, either directly
(`/effort high`) or through a picker that lists zett-agent's own levels: `off`,
`minimal`, `low`, `medium`, `high`, `xhigh` (`xhigh` is what the Responses API
clamps to `high`). The level is per process, not per session, the header shows the one in force beside the model name, and a
change is announced in the transcript between rules, the way a model switch is.

`/context` opens a panel that breaks the next request down by who fills it:

```
Context  25,926 / 128,000 tokens  (20%)
  System prompt        0.2%   (1)
  Environment notes    0.6%   (2)
  Tool schemas         1.2%   (9)
  User messages        0.0%   (3)
  Assistant messages   2.4%  (12)
  Tool output         16.0%  (17)
~4 chars/token · esc back
```

The numbers come from the request the runtime assembled for the last model
call, measured with `tiktoken` when its encoding can be opened and with a
four-characters-per-token estimate otherwise — the footer always names the
counter that produced them. The budget is the compaction threshold, so the
total is also the point at which the agent starts summarizing.
