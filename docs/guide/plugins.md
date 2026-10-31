# Plugins

A plugin is a Python package that adds something to ZettCode: a command, a tool,
a row on the screen, or a change to what the model is asked. Installing the
distribution is the opt-in — there is no registry to edit.

## What a plugin is handed: `ctx`, and three groups

A plugin's `activate(ctx)` gets one context, the same type in every process. What it can register into depends on the
groups that context has:

| Group | Where it exists | What goes in it |
| --- | --- | --- |
| `ctx.agent` | every process | an agent extension, a model provider, an `@` resource, a service others look up |
| `ctx.commands` | every process | a plain command: a name, a summary, a handler whose result is text, a toast or an error — never a page, so any front end can run it |
| `ctx.tui` | only where there is a terminal; `None` otherwise | the commands that open a page or need the shell, palettes, pets, presenters, header and status rows, the line a request ends on |

So a plugin never declares which front end it is for. It registers into a group, and the group is what exists where it
was loaded. One that only adds screen things starts its `activate` with the guard:

```python
from zettcode.app.plugins import PluginContext, TuiPlugin


class Greeter(TuiPlugin):  # the mixin is for the row hooks; the base class is the same Plugin
    name = "greeter"

    def activate(self, ctx: PluginContext) -> None:
        ctx.agent.register_extension(GreeterExtension())
        if ctx.tui is None:
            return
        ctx.tui.register_theme("acme", ACME_THEME)
```

`ctx.commands` is the one to reach for when the answer is words: it is registered for every process, and the terminal
adds it to the command table beside the ones `ctx.tui` holds. A command that opens a page, asks the shell to act, or
waits for a request to end belongs on `ctx.tui` instead.

Nothing is rejected for being for the wrong front end: a plugin always activates, and a broken one — a module that cannot be imported, a name two plugins
claim — is reported as a failure where the reader can see it.

## Installing one

A plugin publishes a class under the `zettcode.plugins` entry-point group:

```toml
[project.entry-points."zettcode.plugins"]
greeter = "my_package:Greeter"
```

```python
from zettcode.app.commands import CommandContext, CommandResult
from zettcode.app.plugins import PluginContext, TuiPlugin


class Greeter(TuiPlugin):
    name = "greeter"
    description = "say hello"

    def activate(self, ctx: PluginContext) -> None:
        if ctx.tui is None:
            return
        ctx.tui.register_command("greet", "say hello", self.greet)

    async def greet(self, context: CommandContext) -> CommandResult:
        return CommandResult(notification=f"hello {context.argument}".strip())
```

Install the plugin into the **same Python environment as ZettCode**, then
restart. The command appears in the `/` menu after the built-in ones.
Installing it into an unrelated virtual environment does not make it available
to a `uv tool` installation.

ZettCode can do the install itself:

```sh
zettcode plugins install /path/to/greeter                  # a local project, wheel or sdist
zettcode plugins install ./greeter.py                      # a single Python file
zettcode plugins install owner/repo                        # a GitHub repository
zettcode plugins install owner/repo@v1.2.0                 # a tag, branch or commit
zettcode plugins install https://github.com/owner/repo/tree/main/plugins/greeter
```

The target is installed into the environment `zettcode` is running in — with
pip, or with uv's pip when that environment has none (as a `uv tool` install
does). A plugin in a subdirectory of a repository is reached with the `tree`
URL shown above. Start ZettCode again and the plugin is in the `/` menu.

A single `.py` file is not installed into site-packages: it is copied into
`~/.zettcode/plugins`, where the next start loads every class it defines that
derives from `Plugin` or `TuiPlugin` — one file can hold more than one, and
there is no name to pass. The file has to be one module (no relative imports),
and it declares no dependencies — install those the way the plugin's
documentation says. Installing over a file with different content is refused
until you pass `--force` (the message says which name it would replace).

```sh
zettcode plugins list                  # every plugin's name, origin, location and switch
zettcode plugins list --json           # the same, for a program to read
zettcode plugins uninstall greeter     # the file's stem, a distribution, or an entry-point name
zettcode plugins disable greeter       # leave it out at the next start
zettcode plugins enable greeter        # load it again
```

`list` shows the program's built-in agent plugins (`compiled in`), the distributions installed beside it (their
entry-point name, distribution and site-packages folder) and the single files in `~/.zettcode/plugins` (their path),
with whether the next start loads each one and the switch that decides it. `ENABLED` is `-` for a compiled-in plugin:
its setting is the switch shown beside it. `uninstall` removes the file from `~/.zettcode/plugins`, or the distribution
behind a name; the name is the distribution's own, the entry-point name
`/plugins` shows as its origin, or the file's stem. `enable` and `disable`
write the same `[plugins] disable` list the `/plugins` panel does; a plugin compiled into
the program is switched by its own setting in the configuration file, which
the panel edits and this command leaves alone.

If you manage the environment yourself, here is the same thing by hand, for a
local plugin project at `/path/to/greeter`:

::: code-group

```bash [uv tool]
uv tool install --force --with /path/to/greeter zettcode
```

```bash [pip in the ZettCode environment]
python -m pip install /path/to/greeter
```

:::

The local project needs its own `pyproject.toml`, an installable Python module,
and the entry point shown above. For a published plugin, use its actual package
name instead of the path. Inside ZettCode, `/greet Ada` then shows a toast saying
`hello Ada`.

To skip it without uninstalling, add this to `config.toml` and restart:

```toml
[plugins]
enabled = true
disable = ["greeter"]
```

`greeter` here is the entry-point name, which can differ from the package name.
`enabled = false` disables all third-party plugins, not the built-in UI.

::: warning Install only trusted plugins
Plugins run Python code in the ZettCode process and can affect both the model
workflow and your local files. They are not sandboxed; review their source and
dependencies before installing them.
:::

## What a plugin can take part in

`Plugin` composes two groups of hooks, and a plugin overrides only the stages it
needs (the agent's group is in `zettcode.engine.plugins`; the screen's is added by
`TuiPlugin` in `zettcode.app.plugins`):

- **The agent's work** — the same lifecycle `zett-agent` extensions use: setup,
  run, turn, model, tool, compaction, and external events. A plugin can register
  tools, rewrite the messages sent to the model, transform a tool result, or
  watch a run finish.
- **The screen** — the header and the status line are each split into a left and
  a right side, and every side is drawn from the segments that registered.

```python
from zettcode.app.plugins import ShellContext, TuiPlugin


class WorkspaceLabel(TuiPlugin):
    """Replace the header's right segment with a model/workspace label."""

    name = "workspace-label"

    def render_header_right(self, context: ShellContext) -> str:
        return f"{context.model.name} · {context.session.workspace.name}"
```

Returning a `str`, a styled `TextLine`, or `None` (draw nothing). A span with no
style of its own inherits the row's muted style, so a segment blends in by
default and opts into colour when it wants to. Registering under a name that
already exists **replaces** that segment in place; a new name is appended after
the ones already on that side. Returning `(value, True)` takes the side over
entirely, which is the way to do it without depending on the built-in names.

Before a model is configured, `context.model.name` is empty, `context.model.efforts`
is empty, and `context.model.config` — the entry itself — is `None`. A segment that
reads the entry should say it has no model rather than assume one is there.

## Writing a command

A command is handed a `CommandContext`:

| Attribute | What it is |
| --- | --- |
| `argument` | The trimmed text after the command name. |
| `ui.markdown(text)` | Append Markdown to the conversation. |
| `ui.notice(text)` / `ui.error(text)` | Add one muted or failing line. |
| `ui.notify(text, level=…)` | Raise a toast. |

The handler returns a `CommandResult` describing what should happen when it
finishes: `message` (Markdown added to the conversation), `notification` (a
toast), `widget` (a page of your own to present over the conversation), and
`relayout` when the change moves the screen around. A slow command can report
progress through `context.ui` while it runs instead of waiting to describe
everything at the end.

Plugin commands are listed last and cannot shadow a built-in, so `/model`,
`/resume` and the rest always do what [Commands](/guide/commands) says.

### Answering with a document

A command registered on `ctx.commands` answers with a `TextCommandResult` or a
`TurnCommandResult` — nothing that needs a terminal. `TextCommandResult` has three fields, all
optional: `message` for a line in the conversation, `notification` for a toast, and `markdown` for
a document the front end shows in a view of its own. Use `markdown` for an answer a reader means
to read rather than scroll past — a report, a review, a page from a plugin's own data — and leave
`message` empty or put a one-line note in it:

```python
from zettcode.engine.plugins.commands import PlainCommandContext, TextCommandResult


def notes(context: PlainCommandContext) -> TextCommandResult:
    """Answer with a document, which the front end shows in a view of its own."""
    return TextCommandResult(markdown="# Notes\n\n- the build is green\n- two things to read")
```

`markdown` is a field rather than a third result type, so nothing written against the older
contract changes: a front end that does not know the field still runs the command and still shows
`message`. What each one does with it:

| Front end | Where a document goes |
| --- | --- |
| The terminal | A page over the conversation: rendered Markdown, scrolled with the arrow keys, closed with Escape. |
| The editor | A Markdown preview beside the chat. |
| The server | `markdown` in the answer to `POST /commands/{name}`; the client draws it. |

`ctx.commands` has no widget and no `CommandUi`, so a document is the most a command can open: a
command that needs a widget of its own, asks a question, or reports as it works belongs on
`ctx.tui` and runs only where there is a terminal.

For example, a command that runs on `ctx.tui` can report progress and answer in Markdown:

```python
async def greet(self, context: CommandContext) -> CommandResult:
    if not context.argument:
        context.ui.error("Usage: /greet <name>")
        return CommandResult()
    context.ui.notice("Preparing a greeting…")
    return CommandResult(message=f"## Hello\n\nWelcome, {context.argument}.")
```

Use this method in place of `Greeter.greet` above. The UI error/notice/result
are displayed in the transcript; they are not a user message submitted to the
model. Prefer the command UI methods to `print()`, which writes outside the
terminal interface.

### Asking the model

A command can run a turn of the conversation — as if the reader had typed it — with
`await context.require_host().prompt(text)`. The text is echoed as the reader's own message, stored in the
session, streamed as it is answered, and settled by the same row; `@` references are resolved, and the command holds
the request slot until the answer is in. It returns `False`, starting nothing, when the text is blank, when the
session is open in another process, or when a request is already running — a command that means to be usable then
declares `when_busy="queue"` (see [While a request is running](#while-a-request-is-running)).

A command whose instructions are longer than what it wants to show passes them apart:
`prompt(brief, shown="/review")` shows `/review` in the conversation — now, and when the session is restored — and
puts the brief in front of the model. The brief stays part of that turn, so the model reads it again on later turns;
only the display is short. `/code-review` is built this way.

This is how a command can be a preset for the model instead of a report about it:

```python
async def review(self, context: CommandContext) -> CommandResult:
    if not context.argument:
        context.ui.error("Usage: /review <what to look at>")
        return CommandResult()
    await context.require_host().prompt(f"Review this change, then list what you would alter. {context.argument}")
    return CommandResult()
```

### Suggesting a first word

A command that takes a fixed first word (`/deploy staging`) can list it, and the completion menu then
offers the words as soon as the command and a space are typed:

```text
ctx.tui.register_command("deploy", "ship a build", self.deploy, subcommands=["staging", "prod"])
```

A name with a description is a `zettcode.app.commands.Subcommand("prod", "the live site")`, and a
function returning the list is asked each time the menu opens, for words that depend on the session.
They only suggest: the handler still receives whatever was typed as `context.argument`, and only the
word right after the command is offered.

### While a request is running

A command typed while a request is running is turned away by default, because most commands change
what that request is standing on. Say otherwise with `when_busy` when you register it:

```text
ctx.tui.register_command("status", "show the build status", self.status, when_busy="now")
```

| `when_busy` | What happens when it is typed during a request |
| --- | --- |
| `"refuse"` (default) | It is turned away with "busy". |
| `"queue"` | It is held and runs the moment the request ends, like `/btw`. |
| `"now"` | It runs at once, beside the request, which carries on undisturbed. |

Say `"now"` only for a command that reads or reports, or changes a setting the request reads when it
needs it. It runs **without** the busy state to itself, so a command that edits the transcript, the
session, or the model the request started with would pull the floor out from under it. Your handler
can be awaited for as long as it likes: the request is not waiting for it, and quitting cancels it.

## Describing a provider {#providers}

A plugin can add a host to the list `/config` offers, so a service ZettCode does not know can be
set up by choosing it and giving a token:

```python
from zettcode.engine.plugins import Plugin, PluginContext
from zettcode.providers import Provider


class Acme(Plugin):
    name = "acme"

    def activate(self, ctx: PluginContext) -> None:
        ctx.agent.register_provider(
            Provider(
                "acme",  # what `/config add acme` is typed with
                "Acme AI",  # what the picker shows
                api="chat",  # chat | responses | anthropic
                base_url="https://api.acme.example/v1",
                token_env="ACME_API_KEY",  # named in the hint only; never read
                note="model ids look like acme-<size>",  # a lower-case phrase, no leading article or full stop
            )
        )
```

A provider describes an address and a protocol and nothing more: nothing is called or connected to,
and the reader still supplies the token and the model id. `models=("acme-small", …)` can suggest
ids to show in the question.

Names are unique across the application. A plugin that registers a name a built-in provider already
has (`openai`, `anthropic`, `deepseek`, `openrouter`, `groq`, `ollama`, `custom`), or one another plugin
registered first, is reported like any other plugin that cannot load.

## Offering a palette {#themes}

A plugin can add palettes to `/theme`. Each one is listed in the menu, previewed as you move through
it, and switched to with `/theme <name>`. ZettCode's own palettes (`nord`, `dracula`, `gruvbox` and the
rest) are offered the same way by a built-in plugin, so this is the whole mechanism:

```text
from pathlib import Path

from zettcode.app.plugins import PluginContext, TuiPlugin


class Palettes(TuiPlugin):
    name = "acme-palettes"

    def activate(self, ctx: PluginContext) -> None:
        # A theme file shipped inside your package: same format as ~/.zettcode/themes/<name>.toml.
        ctx.tui.register_theme("acme", Path(__file__).parent / "acme.toml")
        # Or a function that builds a zettcode.tui.Theme; it runs only when the palette is first asked for.
        ctx.tui.register_theme("acme-night", build_night, description="deep blue, low glare")
```

A name is one word (letters, digits, `.`, `_`, `-`). `dark` and `light` belong to ZettCode. A name a
built-in palette or an earlier plugin already has is reported, like any plugin that cannot
load. A file of the reader's in `~/.zettcode/themes/` with the same name wins over the plugin's, so a
reader can always adjust a palette they were given. A plugin can also be the palette the reader starts
in: `[ui] theme = "acme"` finds it.

## Offering a pet {#pets}

Pets are offered the way palettes are, and the thirteen ZettCode ships (`cat`, `dog`, `tiger`, `polarbear`, `snowbear`, `penguin`,
`scarfy`, `kangaroo`, `seagull`, `whale`, `chibi`, `slime`, `sprout`) are offered by a built-in plugin through the same call. A pet is a palette and the pixel maps of
its moods; each character of a map names a colour, `.` is transparent, and two rows of pixels make one row of
cells, so a map has an even number of rows and every frame of a pet is the same size:

```text
from zettcode.app.pets import Pet
from zettcode.app.plugins import PluginContext, TuiPlugin

PALETTE = {"G": "#84b795", "D": "#263d34", "H": "#e4b47c"}
ASLEEP = ("..GGGG..", ".GGGGGG.", "GGGGGGGG", "GDDGGDDG", "GGGHHGGG", ".GGGGGG.")
AWAKE = ("..GGGG..", ".GGGGGG.", "GGGGGGGG", "GGDGGDGG", "GGGHHGGG", ".GGGGGG.")


class Blobs(TuiPlugin):
    name = "acme-blobs"

    def activate(self, ctx: PluginContext) -> None:
        # The moods are "idle" (required: it is the pet asleep), "working" (while a request runs) and "glad"
        # (when it is patted); a pet that lacks the others stays as it is. A mood with several frames cycles.
        pet = Pet("blob", PALETTE, {"idle": (ASLEEP,), "working": (AWAKE, ASLEEP), "glad": (AWAKE,)})
        ctx.tui.register_pet("blob", pet, description="a quiet green blob")
```

The pet can also be a function that builds one, called the first time it is asked for. A name is one word
(letters, digits, `.`, `_`, `-`); a name a built-in pet or an earlier plugin already has is reported, like
any plugin that cannot load. The pet appears in the `/pet` panel and can be the one the reader starts with:
`[ui] pet = "blob"`.

## Drawing a row {#presenters}

Every row of the conversation is drawn by a *presenter*: an object that turns one kind of entry
into styled lines. The presenters ZettCode ships are registered by a built-in plugin, at the lowest
priority, so a plugin that registers one for the same rows wins without having to outrank anything:

```text
from zettcode.app.agent.conversation.entries import EntryKind
from zettcode.app.agent.conversation.presenters import Presenter
from zettcode.app.plugins import PluginContext, TuiPlugin
from zettcode.tui import Span, Style, TextLine


class QuietNotice(Presenter):
    kind = EntryKind.NOTICE

    def lines(self, entry, width, theme, frame):
        return [TextLine((Span(entry.text, Style(foreground=theme.muted)),))]


class QuietNotices(TuiPlugin):
    name = "quiet-notices"

    def activate(self, ctx: PluginContext) -> None:
        ctx.tui.register_presenter(QuietNotice())
```

A presenter names a `kind` (one member of `EntryKind`), or an `entry_type` when it draws one family
inside a kind — the edit row among the tool rows, say. `lines` receives the entry, the columns
available, the palette, and an animation step, and returns `TextLine`s; a width is a budget, so wrap
or cut. A presenter that animates reads `frame`; one that does not should give the same rows for it.

When more than one presenter could draw the same rows, the higher `priority` wins, and an equal
priority goes to the later registration. That is why the built-ins are the default: priority 0,
registered first. A plugin that wants to beat another plugin raises `priority` on its presenter's
class; drawing only one family never needs a priority, because registering a family is already the
narrower claim. A presenter for a whole kind
claims every row of it, so it beats the families registered before it at its priority; a family
registered after it, or at a higher priority, keeps its own rows.

## Handing the agent a whole extension {#extensions}

The hook methods above run inside one extension that ZettCode hosts for all plugins. A plugin that
already *is* an extension, or wraps one from `zett-agent`, can hand it over whole:

```python
from zettcode.engine.plugins import Plugin, PluginContext


class Audit(Plugin):
    name = "audit"

    def activate(self, ctx: PluginContext) -> None:
        if ctx.config.workspace.name != "scratch":
            ctx.agent.register_extension(AuditExtension())  # a zett_agent AgentExtension
```

The agent receives it beside the others, ordered by the `priority` the extension declares and, among
equals, by the order plugins were loaded. Its `name` must be unique: a plugin that repeats one already
registered, or `plugins`, is reported. An extension that is slow to import, or that needs
the model the agent starts on, is better registered with `ctx.agent.register_extension_factory(name, build)`:
`build` is called when the agent is built, not while the screen is still being drawn, and may return `None`
to add nothing. Everything the agent runs is registered this way: ZettCode's own coding tools, session log,
shell approval, compaction, `ask_user` tool, project instructions, skills, MCP and todo tool are built-in
plugins, so the switches under `[harness]` and the others simply decide whether their plugin registers.

## Turning one off

`/plugins` opens a page with a switch for every plugin you can turn off, the ones compiled into the program first and
the installed ones after them. A single-file plugin in `~/.zettcode/plugins` is one of those installed ones, and it is
listed whether or not it is on — a file switched off stays on the page, off, so it can be switched back on. Up and
Down move, Left, Right and Space flip a switch, Enter writes the changes down and Escape writes nothing. A switch takes
effect at the **next start**: this session does the work it loaded.

Where a switch is written depends on the plugin:

- A plugin **installed beside the program**, including a single file in `~/.zettcode/plugins`, is recorded in
`[plugins] disable` in your `config.toml`. `/plugins disable <name>` and `/plugins enable <name>` do the same for one
name. An older switch file at `~/.zettcode/plugins.json` is still read and merged, so nothing switched off there turns
back on by itself; the next switch written for a name removes it from that file.
- A plugin **compiled into the program** is switched by a setting you already have — `[skills] enabled`, `[mcp]
  enabled`, `[agents_md] enabled`, `[harness] subagent`, `[harness] todowrite`, `[ask_user] enabled` — and the page
  writes that key in your config file. A compiled-in plugin with no such setting is not on the page at all: there would
  be nothing to press. (One that failed to load is still listed, for its reason — that is worth knowing even with
  nothing to press.)

A name in `[plugins] disable` can be switched back on from the page: it is an ordinary switch now, not a line held back
for the reader. The question has one answer wherever it is asked: the terminal's `/plugins` page, the editor's
**ZettCode: Show Plugins** panel and `PUT /plugins/{name}` on the server go through the same rules and write the same
files.

## When something goes wrong

A plugin that cannot be imported or activated is reported, not fatal: the shell
shows `plugin: …` in the transcript and keeps working. Two plugins may not share
an identity, and the second one to claim a command name is reported rather than
silently replacing the first.
