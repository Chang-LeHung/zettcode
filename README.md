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
`ZETTCODE_CONFIG`). The file lists available models; the command line only
names the workspace and, optionally, the session to open:

```bash
zettcode                                    # the workspace defaults to the cwd
zettcode -w /path/to/project                # work somewhere else
zettcode --resume <session-id> [-w DIR]     # open a stored session
zettcode --dry-run                          # run the startup and exit (profiling)
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
context_window = 200000                # tokens this model can carry
compact_percent = 80                   # compact when a request reaches 80%

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
`multimodal` records whether a model accepts images: attaching one — with
`Ctrl-V`, or by pasting a picture the terminal sends as base64 — is refused
with an error when it does not, so a text-only model is never sent one, and it
is not offered `view_image` either: the tool is dropped from the request, so the
model cannot call something that would fail on the way back.
`--dry-run` runs everything the first frame runs — the widget tree, the keymap,
the runtime warming in the background, and one painted frame — prints how long
that took, and exits without taking the terminal. It is the handle to reach for
when profiling startup.

`context_window` is the model's own budget, and `compact_percent` is the share
of it at which a request is compacted; the last quarter of that trigger is kept
verbatim, and `/context` measures against the window. Both default to
`128000` and `80`. Unknown keys and wrong types are reported, not ignored.

```toml
[transcript]
max_entries = 1024                     # conversation rows kept on screen
```

`max_entries` bounds the scrollback, not the conversation: once a session
outgrows it the oldest rows stop being drawn, while `data.jsonl` keeps the whole
tree and the model still gets the full active branch. It defaults to `1024`.

The window comes up before the agent does. The runtime is built in two steps —
settings and session first, the provider SDK and its client when the first
message is sent — so nothing waits on an import to draw the first frame; the
status line reads `ready` while that happens.

`Ctrl-V` attaches an image from the desktop clipboard. A terminal cannot hand
an application the bytes of a pasted image, so the shell reads the clipboard
itself — the pasteboard in-process on macOS, with `osascript` as the fallback
that can coerce a format the pasteboard does not store directly, and `wl-paste`
or `xclip` on Linux, which read the type the clipboard advertises, so PNG,
JPEG, WebP, and GIF all arrive as themselves — and inserts an `[image #N]` chip
into the composer. The chip is text: `Backspace` deletes it in one press,
`Ctrl-Z` puts it back, and the picture is sent as a multimodal part
in the place its chip holds, so text and images keep the order they were
written in and the model reads each picture where the writer put it. Nothing is
written to the workspace: because only the chip is text, a restored session
shows the placeholder where the picture was and does not re-send it.

`Ctrl-V` is the image key and nothing else: every other paste still goes through
the terminal's own paste key (`Cmd-V` on macOS, `Ctrl-Shift-V` or `Alt-V`
elsewhere), which is how text pastes in and where a long one becomes the chip
described below. A terminal that pastes a picture as text instead is recognised
too. VS Code's integrated terminal converts a clipboard image into base64,
warns about the size, and sends the characters; a pasted `data:image/…;base64,`
URI, or bare base64 that decodes to a known image format, becomes the same
`[image #N]` chip rather than a wall of characters standing in for a picture.

Large pastes are handled the same way: a paste longer than 512 characters, or
one taller than the composer grows, becomes a `[pasted text 6012 chars]` chip
instead of pushing the rest of the draft out of view. The full text is restored
when the draft is submitted.

Sessions live in `~/.zettcode/sessions/<base64 workspace path>/`, one append-only
JSONL file per session: every record carries a parent id, so a session is a tree,
and a compaction adds a summary node the active context is cut at. Each workspace
folder also holds `metadata.jsonl`, a small append-only log of titles and activity
times that is folded on read, so listing sessions never parses a conversation.
After the first reply the agent names the session with one small model call and
appends a title line. `/title <name>` names it by hand instead — before the first
message if you like — and that name wins: the background call never renames a
session that already has a title, and `/title` on its own reports the current
one. `/resume` opens a picker panel listing recent sessions with their title and
how long ago they last changed; `Enter` resumes the highlighted one, replacing
the visible transcript with that session's active branch, and
`/resume <id>` restores one directly. The same session can be opened before the
shell starts: `zettcode --resume <id> [-w DIR]`. `/new` clears the visible
conversation. The status line names the active session — `New session` until the
agent titles it, its title afterwards — in place of its short id. Sessions are
not selected in the config file: when the shell exits it prints the
`zettcode --resume …` line for the session that was open, so leaving and coming
back is one copy and paste.

The same line carries the session's token use: `↑22.0k ↓600 · 77.3% cached ·
100 tok/s · ctx 34.0%` reads as cumulative input, cumulative output, the share
of input the provider served from cache, generated tokens per second of model
time, and the share of the model's declared window the newest request filled.
The
numbers come from a usage extension that accumulates the provider's own counters
and publishes them as a custom event after every model call, so the shell
mirrors them without polling; resuming a session seeds the totals from the
usage stored on its branch. The rate is a session average, not an instant
reading.

## Skills and MCP

Two optional capabilities come from the same config file. Both are on by
default and both add nothing to a request until there is something to load.

Skill discovery looks at `[skills] roots` first and then at
`~/.zettcode/skills`; a name declared twice belongs to the earlier directory.
A skill is one directory holding a `SKILL.md` whose front matter declares
`name` and `description`; only that catalog enters the prompt, and a body
arrives when the model calls `read_skill`. A project that ships its own skills
lists them explicitly — `roots = [".zettcode/skills"]` resolves against the
workspace — and `[skills] enabled = false` turns discovery off.

`[mcp] config` points at a JSON file — `~/.zettcode/mcp.json` by default — whose
`servers` (or `mcpServers`) object maps a name to a Streamable HTTP `url` or a
stdio `command`, with optional `args`, `env`, and `cwd`, and `headers` for
HTTP. Their tools are registered as `<server>__<tool>`. No file means no MCP
instructions at all, and `[mcp] enabled = false` turns the extension off.

A stdio server's own output cannot reach the frame: while the app owns the
screen, anything written to stderr — `chrome-devtools-mcp` prints a
banner and a proxy warning on every start — is appended to
`~/.zettcode/log/tui.log` instead of being painted over the conversation.

```toml
[skills]
roots = ["~/team-skills"]      # searched before ~/.zettcode/skills

[mcp]
config = "~/.zettcode/mcp.json"
```

## Plugins

A plugin is a Python distribution that publishes a class under the
`zettcode.plugins` entry-point group. Installing it is the opt-in; the class
subclasses `zettcode.plugins.Plugin` and takes part in the agent exactly like
the extensions ZettCode ships. `Plugin` composes two groups of hooks:
`PluginAgentMixin` carries the whole model/tool lifecycle — setup, run, turn,
model, tool, compaction, external events, and the model/tool middleware, the
same grouping `zett-agent`'s extension mixins use — and `PluginUiMixin` fills
the shell's four row slots. A plugin overrides only the stages it cares
about, and also registers the slash commands the shell then offers and runs.

```toml
[project.entry-points."zettcode.plugins"]
greeter = "my_package:Greeter"
```

```python
from zettcode.plugins import CommandContext, CommandResult, Plugin, PluginContainer


class Greeter(Plugin):
    name = "greeter"

    def activate(self, container: PluginContainer) -> None:
        container.register_command("greet", "say hello", self.greet)

    async def greet(self, context: CommandContext) -> CommandResult:
        return CommandResult(notification=f"hello {context.argument}".strip())
```

The hooks receive the same values an extension does — `AgentRunContext`,
`ModelRequest`, `ToolCall`, and so on — so a plugin can register tools, rewrite
the messages sent to the model, transform tool results, or observe a finished
run. A command is handed a `CommandContext`: `context.argument` is the trimmed
text after the name, and `context.ui` writes while the command runs —
`ui.markdown` appends Markdown to the conversation, `ui.notice` and `ui.error`
add a line, `ui.notify` raises a toast — so a slow command can report its
progress instead of waiting to describe everything in its `CommandResult`.
Plugin commands are listed last, so a plugin cannot shadow a built-in such as
`/model`.

Plugins also own the shell's rows. The header and the status line are each
split into a left and a right side, and every side is drawn from the segments
the merged bundle registered: the builtin `ShellRows` plugin supplies the
defaults, and `ZettCodeApp` only joins what it finds. A plugin takes a slot
over by overriding the builder for it, because the method name is the segment
name the override registers under. Returning ``(line, True)`` is the stronger
form: it drops whatever the segments before it painted on that side, so the
plugin does not have to know the builtin's names at all.

```python
from zettcode.plugins import Plugin, ShellContext


class Branch(Plugin):
    name = "branch"

    def render_header_right(self, context: ShellContext) -> str:
        return f"main {context.model.name}  "
```

A plugin that wants a segment of its own beside the defaults registers it into
one of the four slots; reusing a name that already exists in the row replaces
that segment in place, while a new name appends after the segments already in
its side. ``override=True`` clears the side first, leaving the plugin's segment
as the only one there — the safe way to take a side over without depending on
the builtin's names. Every call returns ``(segment, displaced)``, where
``displaced`` says whether it took an existing segment's place:

```python
from zettcode.plugins import Plugin, PluginContainer, ShellContext, Span, Style, TextLine


class Tokens(Plugin):
    name = "tokens"

    def activate(self, container: PluginContainer) -> None:
        container.register_status_right(self.draw, name="tokens")

    def draw(self, context: ShellContext) -> TextLine:
        muted = Style(foreground=context.display.theme.muted)
        word = "working" if context.activity.busy else context.session.name
        return TextLine((Span(f" {context.model.name} {word}", muted),))
```

The builder runs once per paint with a `ShellContext` carrying everything the
shell's own rows read, grouped by what it describes:

- `session` — id, title, display name, workspace;
- `model` — the active `ModelConfig`, its display name, the effort in force and
  the levels available;
- `activity` — busy flag, status word, auto-approval mode, token counters, the
  current plan, and the animation frame;
- `display` — active theme, terminal size, topmost screen name, and whether the
  transcript is scrolled up;
- plus the resolved `config` at the top level.

It returns a `str`, a styled `TextLine`, or `None` to draw nothing. A span with
no style of its own inherits the row's muted style, so a plugin blends in by
default and opts into colour when it wants it.

Plugins are discovered at startup and activated in entry-point name order. One
that cannot be imported or activated is skipped, not fatal: the shell shows a
`plugin: …` line in the transcript and keeps the rest of the session working.
Every plugin rides in one host extension, in priority order, so the agent sees
a single extension while plugin-wide behaviour keeps one place to live. A
plugin is identified by the `name` it declares and otherwise by its entry-point
name; two plugins may not share an identity, and the second one to claim a
command name is skipped rather than silently shadowed. The builtin rows are a
plugin too, so it always loads; the `[plugins]` table only governs the
distributions, switching them all off or holding one back by its entry-point
name.

```toml
[plugins]
enabled = true
disable = ["greeter"]          # entry-point names not to load
```

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
uv run zettcode -w /path/to/project
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
- `Ctrl-V`: attach an image from the system clipboard; text pastes keep using
  the terminal's own paste key
- `Page Up` / `Page Down`: scroll history while keeping the composer focused
- `Esc` or the `↓ back to bottom` badge: jump to the newest line once scrolled up
- Mouse wheel: scroll history
- Click a Thinking or Tool row to expand or collapse it
- Drag in the transcript to select text; the selection is copied on release,
  and moving past its edge keeps extending it instead of dropping the drag
- Drag anywhere else — a panel, a list, the header, the status line — to copy
  the text painted there; those surfaces never had selectable text of their own
- Double-click a transcript row to select the whole line
- `Shift`-click to extend the existing selection
- `Ctrl-C` copies the current selection — transcript or panel — and clears it;
  on a panel it copies rather than closing the page while a selection is live
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
`Processed for 51s · 09:41`, `Processed for 22m 30s · 14:05`, or
`Processed for 2h 5m 7s · 18:30`.

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

Neither built-in palette paints a page: those cells are left to the terminal's
own background, so the shell blends into whatever profile you run, and only the
surfaces it means to raise — the composer band, a user message, the plan box —
carry a colour. That is also why the startup detection matters: a light palette
on a light terminal is what keeps the text readable when nobody paints a page.
`[ui] background = "#232a2e"` in a theme file makes a palette paint one.

The terminal's window or tab name follows the session: it is the session title
once there is one, and `zettcode · <workspace>` before that. It is released when
the shell exits, so a prompt that sets its own title takes over again. VS Code
only lends the tab name to processes it recognises, so add `${sequence}` to
`terminal.integrated.tabs.title` there; iTerm2 needs no setting.

Use `/help` inside the application to see session commands; `/new`, `/resume`,
`/title`, `/model`, `/effort`, `/theme`, `/context`, `/compact`, `/export`,
`/clear`, and `/quit` are available.
The composer command menu identifies each command as `app` or `agent`, shows
its description, and scrolls when there are more matches than visible rows.

`/export [path]` writes the session — and the request the next turn would send —
to one self-contained HTML file: a sidebar of turns, the selected turn's events
on the right, each event carrying the raw text it was written with, the time it
was written, and what it cost. Long text — the system prompt, a wall of tool
output — starts collapsed and opens into a block that scrolls instead of
stretching the page. The last entry in the sidebar is the current
context, so the file answers both "what was said" and "what the model is
carrying now"; a compacted session shows the checkpoint there, and a repeated
system instruction is pointed at rather than printed again. Without a path the
file lands in the workspace as `zettcode-<session-id>.html`.

`/effort` sets how much the model reasons before it answers, either directly
(`/effort high`) or through a picker that lists zett-agent's own levels: `off`,
`minimal`, `low`, `medium`, `high`, `xhigh`, `max`, and `ultra`. A provider maps
a level it cannot express onto its closest supported value, so the deepest
levels degrade rather than fail. The level is per process, not per session, the
header shows the one in force beside the model name, and a change is announced
in the transcript between rules, the way a model switch is.

`/context` opens a panel that breaks the next request down by who fills it:

```
Context  103,241 / 128,000 tokens
  Source              Share    Count
  System prompt        1.9%      (1)
  Environment notes    4.8%      (2)
  Tool schemas        10.9%      (9)
  User messages        0.1%      (3)
  Assistant messages  22.2%     (12)
  Tool output         60.1%     (17)
~4 chars/token · esc back
```

The numbers come from the request the runtime assembled for the last model
call, measured with `tiktoken` when its encoding can be opened and with a
four-characters-per-token estimate otherwise — the footer always names the
counter that produced them. A row's percentage is its share of the context in
use, so the rows add up to 100%; the title compares the total against the
model's `context_window`, not against the point at which compaction fires.

`/compact` summarizes the conversation there and then, instead of waiting for
the context to grow past that point. The work is the runtime's own — the same
cutoff, the same summary call, the same checkpoint — with one difference: a
manual pass keeps only the last turn verbatim where an automatic one leaves a
quarter of the trigger behind. The command calls `AgentClient.compact`, which
restores the session, runs the pass, and dispatches its events; no message is
appended for it and no primary model call is made, so the conversation is left
exactly as it was, only shorter.

The summarizer gets its own animated row — the same blink, sweep, and timer a
Thinking row has, labelled `Compacting`, with the summary streaming under it —
followed by `Context compaction applied` or `Context compaction skipped` when
the summary would not be smaller. The checkpoint is stored on the session's
branch, so a later `/resume` picks the session up from it.
