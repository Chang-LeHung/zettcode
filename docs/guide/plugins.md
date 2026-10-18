# Plugins

A plugin is a Python package that adds something to ZettCode: a command, a tool,
a row on the screen, or a change to what the model is asked. Installing the
distribution is the opt-in — there is no registry to edit.

## Installing one

A plugin publishes a class under the `zettcode.plugins` entry-point group:

```toml
[project.entry-points."zettcode.plugins"]
greeter = "my_package:Greeter"
```

```python
from zettcode.app.commands import CommandContext
from zettcode.plugins import CommandResult, Plugin, PluginContainer


class Greeter(Plugin):
    name = "greeter"
    description = "say hello"

    def activate(self, container: PluginContainer) -> None:
        container.register_command("greet", "say hello", self.greet)

    async def greet(self, context: CommandContext) -> CommandResult:
        return CommandResult(notification=f"hello {context.argument}".strip())
```

Install the plugin into the **same Python environment as ZettCode**, then
restart. The command appears in the `/` menu after the built-in ones.
Installing it into an unrelated virtual environment does not make it available
to a `uv tool` installation.

For example, if you have a local plugin project at `/path/to/greeter`:

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
needs:

- **The agent's work** — the same lifecycle `zett-agent` extensions use: setup,
  run, turn, model, tool, compaction, and external events. A plugin can register
  tools, rewrite the messages sent to the model, transform a tool result, or
  watch a run finish.
- **The screen** — the header and the status line are each split into a left and
  a right side, and every side is drawn from the segments that registered.

```python
from zettcode.plugins import Plugin, ShellContext


class WorkspaceLabel(Plugin):
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

For example, a command can report progress or render a Markdown result:

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

### Suggesting a first word

A command that takes a fixed first word (`/deploy staging`) can list it, and the completion menu then
offers the words as soon as the command and a space are typed:

```text
container.register_command("deploy", "ship a build", self.deploy, subcommands=["staging", "prod"])
```

A name with a description is a `zettcode.app.commands.Subcommand("prod", "the live site")`, and a
function returning the list is asked each time the menu opens, for words that depend on the session.
They only suggest: the handler still receives whatever was typed as `context.argument`, and only the
word right after the command is offered.

### While a request is running

A command typed while a request is running is turned away by default, because most commands change
what that request is standing on. Say otherwise with `when_busy` when you register it:

```text
container.register_command("status", "show the build status", self.status, when_busy="now")
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
from zettcode.plugins import Plugin, PluginContainer
from zettcode.providers import Provider


class Acme(Plugin):
    name = "acme"

    def activate(self, container: PluginContainer) -> None:
        container.register_provider(
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
registered first, is skipped and reported like any other plugin that cannot load.

## Offering a palette {#themes}

A plugin can add palettes to `/theme`. Each one is listed in the menu, previewed as you move through
it, and switched to with `/theme <name>`. ZettCode's own palettes (`nord`, `dracula`, `gruvbox` and the
rest) are offered the same way by a built-in plugin, so this is the whole mechanism:

```text
from pathlib import Path

from zettcode.plugins import Plugin, PluginContainer


class Palettes(Plugin):
    name = "acme-palettes"

    def activate(self, container: PluginContainer) -> None:
        # A theme file shipped inside your package: same format as ~/.zettcode/themes/<name>.toml.
        container.register_theme("acme", Path(__file__).parent / "acme.toml")
        # Or a function that builds a zettcode.tui.Theme; it runs only when the palette is first asked for.
        container.register_theme("acme-night", build_night, description="deep blue, low glare")
```

A name is one word (letters, digits, `.`, `_`, `-`). `dark` and `light` belong to ZettCode. A name a
built-in palette or an earlier plugin already has is skipped and reported, like any plugin that cannot
load. A file of the reader's in `~/.zettcode/themes/` with the same name wins over the plugin's, so a
reader can always adjust a palette they were given. A plugin can also be the palette the reader starts
in: `[ui] theme = "acme"` finds it.

## Offering a pet {#pets}

Pets are offered the way palettes are, and the thirteen ZettCode ships (`cat`, `dog`, `tiger`, `polarbear`, `snowbear`, `penguin`,
`scarfy`, `kangaroo`, `seagull`, `whale`, `chibi`, `slime`, `sprout`) are offered by a built-in plugin through the same call. A pet is a palette and the pixel maps of
its moods; each character of a map names a colour, `.` is transparent, and two rows of pixels make one row of
cells, so a map has an even number of rows and every frame of a pet is the same size:

```text
from zettcode.plugins import Pet, Plugin, PluginContainer

PALETTE = {"G": "#84b795", "D": "#263d34", "H": "#e4b47c"}
ASLEEP = ("..GGGG..", ".GGGGGG.", "GGGGGGGG", "GDDGGDDG", "GGGHHGGG", ".GGGGGG.")
AWAKE = ("..GGGG..", ".GGGGGG.", "GGGGGGGG", "GGDGGDGG", "GGGHHGGG", ".GGGGGG.")


class Blobs(Plugin):
    name = "acme-blobs"

    def activate(self, container: PluginContainer) -> None:
        # The moods are "idle" (required: it is the pet asleep), "working" (while a request runs) and "glad"
        # (when it is patted); a pet that lacks the others stays as it is. A mood with several frames cycles.
        pet = Pet("blob", PALETTE, {"idle": (ASLEEP,), "working": (AWAKE, ASLEEP), "glad": (AWAKE,)})
        container.register_pet("blob", pet, description="a quiet green blob")
```

The pet can also be a function that builds one, called the first time it is asked for. A name is one word
(letters, digits, `.`, `_`, `-`); a name a built-in pet or an earlier plugin already has is skipped and reported, like
any plugin that cannot load. The pet appears in the `/pet` panel and can be the one the reader starts with:
`[ui] pet = "blob"`.

## Drawing a row {#presenters}

Every row of the conversation is drawn by a *presenter*: an object that turns one kind of entry
into styled lines. The presenters ZettCode ships are registered by a built-in plugin, at the lowest
priority, so a plugin that registers one for the same rows wins without having to outrank anything:

```text
from zettcode.plugins import EntryKind, Plugin, PluginContainer, Presenter, Span, Style, TextLine


class QuietNotice(Presenter):
    kind = EntryKind.NOTICE

    def lines(self, entry, width, theme, frame):
        return [TextLine((Span(entry.text, Style(foreground=theme.muted)),))]


class QuietNotices(Plugin):
    name = "quiet-notices"

    def activate(self, container: PluginContainer) -> None:
        container.register_presenter(QuietNotice())
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
from zettcode.plugins import Plugin, PluginContainer


class Audit(Plugin):
    name = "audit"

    def activate(self, container: PluginContainer) -> None:
        if container.config.workspace.name != "scratch":
            container.register_extension(AuditExtension())  # a zett_agent AgentExtension
```

The agent receives it beside the others, ordered by the `priority` the extension declares and, among
equals, by the order plugins were loaded. Its `name` must be unique: a plugin that repeats one already
registered, or `plugins`, is skipped and reported. An extension that is slow to import, or that needs
the model the agent starts on, is better registered with `container.register_extension_factory(name, build)`:
`build` is called when the agent is built, not while the screen is still being drawn, and may return `None`
to add nothing. Everything the agent runs is registered this way: ZettCode's own coding tools, session log,
shell approval, compaction, `ask_user` tool, project instructions, skills, MCP and todo tool are built-in
plugins, so the switches under `[harness]` and the others simply decide whether their plugin registers.

## When something goes wrong

A plugin that cannot be imported or activated is skipped, not fatal: the shell
shows `plugin: …` in the transcript and keeps working. Two plugins may not share
an identity, and the second one to claim a command name is skipped rather than
silently replacing the first.
