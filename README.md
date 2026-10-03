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
panel and returns to the composer.
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
appends a title line. `/sessions` opens a picker panel listing recent sessions with
their title and how long ago they last changed; `Enter` resumes the highlighted one,
and `/use <id>` still switches directly. Sessions are not selected in the config
file.

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
accent = "#79b88b"

[code]
keyword = "#e58fa8"
string = "#9bddad"
comment = "#6d7a70"
number = "#d8b46a"
function = "#7fb7d8"
builtin = "#b8a6e0"
inline = "#9bddad"
```

Unknown keys and malformed colours are reported instead of silently ignored.
`/theme dark|light` still switches the base palette at runtime.

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
elapsed time in tenths — nothing else moves while the model works, so that count
is the only sign of progress — and is replaced by the real answer, reasoning, or
tool call as soon as one arrives. A request waits more than once: every tool batch is
followed by another model call, and `Processing` comes back below the rows it
belongs to until that call answers. Rows that are still running show the same
elapsed timer, and when the
turn ends the transcript closes with a muted summary of the wall time it took:
`Processed 51s · 09:41`, `Processed 22m · 14:05`, or `Processed 2h 5m · 18:30`.

Assistant text renders common terminal-friendly Markdown: bold and emphasis,
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

Use `/help` inside the application to see session commands; `/new`, `/sessions`,
`/use`, `/model`, `/theme dark|light`, `/clear`, and `/quit` are available.
The composer command menu identifies each command as `app` or `agent`, shows
its description, and scrolls when there are more matches than visible rows.
