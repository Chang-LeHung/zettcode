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
from zettcode.plugins import CommandContext, CommandResult, Plugin, PluginContainer


class Greeter(Plugin):
    name = "greeter"
    description = "say hello"

    def activate(self, container: PluginContainer) -> None:
        container.register_command("greet", "say hello", self.greet)

    async def greet(self, context: CommandContext) -> CommandResult:
        return CommandResult(notification=f"hello {context.argument}".strip())
```

Then `pip install` it and start ZettCode: the command appears in the `/` menu
after the built-in ones. `[plugins] enabled = false` turns them all off, and
`disable = ["greeter"]` holds one back without uninstalling it.

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


class Branch(Plugin):
    """Show the current git branch in the header."""

    name = "branch"

    def render_header_right(self, context: ShellContext) -> str:
        return f"main {context.model.name}  "
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

## When something goes wrong

A plugin that cannot be imported or activated is skipped, not fatal: the shell
shows `plugin: …` in the transcript and keeps working. Two plugins may not share
an identity, and the second one to claim a command name is skipped rather than
silently replacing the first.
