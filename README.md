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

## Run

DeepSeek:

```bash
export DEEPSEEK_API_KEY=...
zettcode --provider deepseek --model deepseek-chat
```

OpenAI or an OpenAI-compatible endpoint:

```bash
export OPENAI_API_KEY=...
zettcode --provider openai --model gpt-5-mini
zettcode --provider openai --model my-model --base-url https://example.com/v1
```

Pass a workspace path as the final argument. It defaults to the current directory.
Sessions live in `~/.zettcode/sessions/`, one append-only JSONL file per session:
every record carries a parent id, so a session is a tree, and a compaction adds a
summary node the active context is cut at. `--store` points that directory
somewhere else.

## Approvals

`run_shell` asks for confirmation before it executes anything. The prompt offers
Run, Always (remember this exact command), and Abort, and `Esc` aborts. Pass
`--approval allow-all` to let the agent run shell commands without asking.

The agent's plan, when it publishes one, appears above the composer. Pass
`--reduced-motion` (or set `ZETTCODE_REDUCED_MOTION`) to suppress decorative
animation.

## Colours

Everything is drawn from theme tokens, so a palette can be overridden without
touching code. `zettcode` reads `~/.zettcode/theme.toml` when it exists, or any
path passed to `--theme-file`:

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
inline = "#d8c07a"
```

Unknown keys and malformed colours are reported instead of silently ignored.
`/theme dark|light` still switches the base palette at runtime.

From a source checkout, run the same commands through `uv`:

```bash
uv sync
uv run zettcode --provider deepseek --model deepseek-chat
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

Pressing Enter puts a live row in the transcript straight away, so a slow model
is never mistaken for a frozen one. It shows an animated glyph and the elapsed
time, and is replaced by the real answer, reasoning, or tool call as soon as one
arrives. Rows that are still running show the same elapsed timer.

Assistant text renders common terminal-friendly Markdown: bold and emphasis,
headings, inline and fenced code, links, quotes, unordered bullet lists, and
GFM-style tables. Code is highlighted by colour only, never by a background
block. Tables are borderless — a header, one rule per column, then rows — keep
left, center, and right alignment, account for wide CJK characters, and wrap a
cell that does not fit instead of cutting its text.

Use `/help` inside the application to see session commands; `/new`, `/sessions`,
`/use`, `/theme dark|light`, `/clear`, and `/quit` are available.
