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

## When something goes wrong

A plugin that cannot be imported or activated is skipped, not fatal: the shell
shows `plugin: …` in the transcript and keeps working. Two plugins may not share
an identity, and the second one to claim a command name is skipped rather than
silently replacing the first.
