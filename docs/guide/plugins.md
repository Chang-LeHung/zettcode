# Plugins

A plugin is a Python package that adds something to ZettCode: a command, a tool,
a row on the screen, or a change to what the model is asked. Installing the
distribution is the opt-in — there is no registry to edit.

## How this page is organised

Read the first three sections to learn the model, then use the recipes for the
thing you want to build:

| If you want to… | Read |
| --- | --- |
| understand what happens from install to a running plugin | [How a plugin loads](#how-a-plugin-loads) |
| see one complete, working plugin | [A complete plugin](#a-complete-plugin) |
| know what `ctx` and the services give you | [The context and its services](#the-context-and-its-services) |
| add a command, row, palette, pet, provider, tool or trigger | the sections below and [Plugin API reference](#plugin-api-reference) |
| declare settings or command-line flags | [Reading the configuration](#reading-the-configuration), [Command-line flags](#command-line-flags) |
| understand failures, ordering and dependencies | [Depending on another plugin](#deps), [When something goes wrong](#when-something-goes-wrong) |

## How a plugin loads

The unit is a Python distribution with an entry point — or a single `.py` file in `~/.zettcode/plugins`:

```toml
[project.entry-points."zettcode.plugin"]
journal = "my_package.plugin:Journal"
```

The word on the left (`journal`) is the plugin's **origin**. It is what
`[plugins] disable` names and what the `PLUGIN_CLI` values are grouped under.
The class on the right is a `Plugin` subclass. Its `name` is the plugin's
identity, and defaults to the entry-point name. Settings live under
`[plugins.<name>]` and `deps` use `name`; the `[plugins] disable` switch and
`/plugins` match the **origin** (the entry-point name), even when a plugin
declares a different `name`. This distinction matters when a package is
renamed. The loader does this once, in order:

1. Discover installed entry points and single files in `~/.zettcode/plugins`.
2. Instantiate each class. The constructor should be cheap and should not read
   the workspace or call a model.
3. Build a `PluginContext` for that plugin and call `activate(ctx)`. This is
   synchronous on purpose: it must only register what the plugin contributes,
   never await or start work, so every registration is complete before the shell
   or agent is built.
4. Check the contributions for duplicate command, extension, service, theme,
   pet, trigger and provider names.
5. Merge them into the application. `Plugin` hooks run inside one host
   extension; whole extensions registered with `register_extension()` run
   beside it.
6. On shutdown, call `await plugin.aclose()` once, newest plugin first.

The loader is deliberately forgiving: a plugin that cannot be imported or
activated is reported as `plugin: …`, and the rest of the application keeps
working. Dependencies and ordering are covered in
[Depending on another plugin](#deps).

A plugin is not a terminal plugin or a server plugin. It receives the same
`PluginContext` everywhere; `ctx.tui` is simply `None` in a process without a
screen. Write the portable part against `ctx.agent`, `ctx.commands` and
services, and guard screen work with:

```text
if ctx.tui is None:
    return
```

The loader does not filter plugins by front end. A plugin is activated in every
process that loads it, so screen-only work must be behind that guard; otherwise
activation fails and its other registrations are discarded.

## A complete plugin

This plugin adds a `/journal` plain command, declares one setting and one
startup flag, and reads the service the application hands it. It is complete:
save it as `plugin.py`, add the entry point above, install the package and
restart.

```python
from zettcode.plugin_api import (
    PLUGIN_CLI,
    CliOption,
    PlainCommandContext,
    Plugin,
    PluginContext,
    TextCommandResult,
)


class Journal(Plugin[PluginContext]):
    name = "journal"
    description = "Keep a short, local journal of what this session is doing"

    @classmethod
    def cli_arguments(cls) -> tuple[CliOption, ...]:
        """Read before activation; values arrive in the PLUGIN_CLI service."""
        return (
            CliOption(
                ("--journal-limit",),
                "limit",
                help="how many recent entries to show",
                default="3",
                metavar="N",
            ),
        )

    def activate(self, ctx: PluginContext) -> None:
        given = ctx.settings.declare(prefix="session")
        cli = ctx.service(PLUGIN_CLI, dict).get("journal", {})
        self.prefix = str(given["prefix"])
        self.limit = int(cli.get("limit", "3"))
        ctx.commands.register("/journal", "show recent journal entries", self.show)

    async def show(self, context: PlainCommandContext) -> TextCommandResult:
        if not context.argument:
            return TextCommandResult(message=f"{self.prefix}: nothing chosen")
        return TextCommandResult(
            message=f"## {self.prefix}\n\nLast {self.limit} entries about: {context.argument}"
        )
```

Run `zettcode --journal-limit 5`; type `/journal tests` in the composer. The
same plugin is available to a daemon started with
`zettcode daemon spawn --journal-limit 5`.

## The context and its services

`PluginContext` is the plugin's only channel to the application. Its attributes
are short, typed aliases over services; both forms are supported:

```text
ctx.config is ctx.service(PLUGIN_CONFIG, ZettCodeConfig)
ctx.agent is ctx.service(PLUGIN_AGENT, AgentGroups)
ctx.commands is ctx.service(PLUGIN_COMMANDS, CommandGroups)
ctx.tui is ctx.find(PLUGIN_TUI, TuiGroup)       # None without a screen
```

### What the context gives you

| Member | Type | Use |
| --- | --- | --- |
| `ctx.config` | `ZettCodeConfig` | resolved settings; read-only |
| `ctx.workspace` | `Path` | the directory this session works in |
| `ctx.settings` | `PluginSettings` | declare and read `[plugins.<name>]` keys |
| `ctx.agent` | `AgentGroups` | extensions, providers, mentions, triggers, services |
| `ctx.commands` | `CommandGroups` | plain commands that work in every front end |
| `ctx.tui` | `TuiGroup \| None` | terminal-only commands, rows, themes, pets, presenters |
| `ctx.service(name, kind)` | `T` | a required service; raises `LookupError` when absent |
| `ctx.find(name, kind)` | `T \| None` | an optional service; `None` when absent |
| `ctx.provide(name, value)` | `object` | publish a service for later plugins |

`ctx.service` and `ctx.find` verify the `kind`. A wrong type is a `TypeError`,
not a silent `None`. `ctx.provide` refuses a name already provided by this
plugin, one of the six context-owned names, or a blank name; the loader refuses
a service name another plugin already published.

### Services the application provides

The names are constants exported by `zettcode.plugin_api`. Availability is the
important part: the screen and messaging services are not present in every
process.

| Service | Type | Available when | Use |
| --- | --- | --- | --- |
| `PLUGIN_AGENT` | `AgentGroups` | always | extension/provider/mention/trigger registration |
| `PLUGIN_COMMANDS` | `CommandGroups` | always | plain `/commands` |
| `PLUGIN_TUI` | `TuiGroup` | terminal only | screen commands, rows, themes, pets, presenters |
| `PLUGIN_CONFIG` | `ZettCodeConfig` | always | resolved configuration |
| `PLUGIN_WORKSPACE` | `Path` | always | session workspace |
| `PLUGIN_SETTINGS` | `PluginSettings` | always | this plugin's settings table |
| `LLM` | `ModelAccess` | engine | `.models` and `.ask(...)` side questions |
| `PLUGIN_CLI` | `dict[str, dict[str, object]]` | engine | parsed plugin command-line flags |
| `HOST_LINK` | `HostLink` | terminal | late-bound `CommandHost` for TUI commands |
| `INBOX` | `Inbox` | messaging plugin loaded | hand an event to the session |
| `SESSION_STORE` | `SessionStoreService` | engine | list stored sessions |
| `USAGE_LEDGER` | `UsageLedgerService` | engine | read token usage |
| `CONTEXT_REPORT` | `ContextReportService` | engine | context report for a session |
| `CONTEXT_PAGE` | `ContextPageService` | engine | `/context` page data and writer |
| `MODELS` | provider adapters keyed by `ModelConfig` | engine | the models built so far |
| `CAPABILITIES` | `ModelCapabilities` | built-in capabilities plugin | model-specific tool filtering |
| `POLICY` | `ShellPolicy` | engine | current shell permission policy |
| `PERSISTENCE` | `SessionStore` | engine | the storage implementation |
| `COMPACTION_COUNTER` | `CompactionCounter` | engine | token accounting |
| `SELECTED_MODEL` | `ModelConfig` | engine, when a model is configured | the model the next run uses |
| `APPROVAL`, `USAGE`, `CONTEXT`, `SIDES`, `COMPACTION`, `TODOS` | engine contracts | built-in feature plugins | feature services |

`HARNESS` and `DELIVERY` are internal engine services and not part of the plugin contract; there is no typed
reader for them.
The types in this table are exported by `zettcode.plugin_api` (the contracts live in `zettcode.engine`).

Use `ctx.find` for anything a plugin may or may not provide, especially `INBOX`,
`HOST_LINK`, `SELECTED_MODEL`, and the page services. Use `ctx.service` only
when the plugin's README says its dependency provides it. A missing required
service is a clear `LookupError`, not a silent default.

### Model access

`LLM` is the service for a plugin that needs a model answer without starting a
turn:

```text
from zettcode.plugin_api import LLM, ModelAccess

access = ctx.service(LLM, ModelAccess)
for model in access.models:
    ...
answer = await access.ask("Summarise the failing test", origin="journal")
```

The question is a side question: it does not join the conversation, and a
resumed transcript does not restore a plugin's question. The full signature is
`ask(question, *, origin="plugin", cache="read", timeout=None)`. `LLM.ask`
raises `RuntimeError` before the front end has bound the conversation; it
cannot be used inside `activate`, only once a request can run. The plugin gets
the model of the current run through the run context; `ModelAccess` does not
change the reader's selected model.

## Installing one

A plugin publishes a class under the `zettcode.plugin` entry-point group; the loader accepts a class, a zero-argument factory, or an instance, and a class is the usual form:

```toml
[project]
name = "my-package"
dependencies = ["zettcode-plugin-api>=0.4,<0.5"]

[project.entry-points."zettcode.plugin"]
greeter = "my_package:Greeter"
```

`zettcode-plugin-api` is the one dependency a plugin needs, and it carries everything the plugin runs against. If
you annotate with SDK types, import them from the module that owns them: `Client` from `zettcode.sdk`,
`ModelInfo` from `zettcode.sdk.types`, and `Usage` from either. Those modules are not installed by
`zettcode-plugin-api` alone. In a CI or lint environment that
installs only your package, use the extra
`dependencies = ["zettcode-plugin-api[types]>=0.4,<0.5"]`, which pulls `zettcode-sdk`. Without it mypy cannot resolve
those imports unless `ignore_missing_imports` is set; nothing changes at run time. `Theme` in a palette or presenter
annotation comes from `zettcode.tui`, which is installed with `zettcode-plugin-api`.

```python
from zettcode.plugin_api import CommandContext, CommandResult
from zettcode.plugin_api import PluginContext, TuiPlugin


class Greeter(TuiPlugin):
    name = "greeter"
    description = "say hello"

    def activate(self, ctx: PluginContext) -> None:
        if ctx.tui is None:
            return
        ctx.tui.register_command("greet", "say hello", self.greet)

    async def greet(self, context: CommandContext) -> CommandResult:
        return CommandResult(notification=f"hello {context.argument}")
```

Install the plugin into the **same Python environment as ZettCode**, then
restart. The command appears in the `/` menu after the built-in ones.
Installing it into an unrelated virtual environment does not make it available
to a `uv tool` installation.

ZettCode can do the install itself:

```sh
zettcode plugin install /path/to/greeter                  # a local project, wheel or sdist
zettcode plugin install ./greeter.py                      # a single Python file
zettcode plugin install owner/repo                        # a GitHub repository
zettcode plugin install owner/repo@v1.2.0                 # a tag, branch or commit
zettcode plugin install https://github.com/owner/repo/tree/main/plugins/greeter
```

The target is installed into the environment `zettcode` is running in — with
pip, or with uv's pip when that environment has none (as a `uv tool` install
does). A plugin in a subdirectory of a repository is reached with the `tree`
URL shown above. Start ZettCode again and the plugin is in the `/` menu.

A single `.py` file is not installed into site-packages: it is copied into
`~/.zettcode/plugins`, where the next start loads every class it defines that
derives from `Plugin` or `TuiPlugin` — one file can hold more than one, but each
class needs a distinct `name`; a class with none falls back to the file stem, so two such classes clash. The file has to be one module (no relative imports),
and it declares no dependencies — install those the way the plugin's
documentation says. Installing over a file with different content is refused
until you pass `--force` (the message names the target path and says to remove it first or pass --force).

```sh
zettcode plugin list                  # every plugin's name, origin, location and switch
zettcode plugin list --json           # the same, for a program to read
zettcode plugin uninstall greeter     # the file's stem, a distribution, or an entry-point name
zettcode plugin disable greeter       # leave it out at the next start
zettcode plugin enable greeter        # load it again
```

`list` shows the program's built-in agent plugins (`compiled in`), the distributions installed beside it (their
entry-point name, distribution and site-packages folder) and the single files in `~/.zettcode/plugins` (their path),
with whether the next start loads each one and the switch that decides it. The program's own terminal parts
(`themes`, `pets`, `context`, `usage`) are listed by the `/plugins` page, not by this command. `ENABLED` is `-` for a compiled-in plugin:
its setting is the switch shown beside it. `uninstall` removes the file from `~/.zettcode/plugins`, or the distribution
behind a name; the name is the distribution's own, the entry-point name
`/plugins` shows as its origin, or the file's stem. `enable` and `disable`
write the same `[plugins] disable` list the `/plugins` panel does, for the plugins this command accepts; the panel
also lists the program's optional terminal parts, which this command does not. A plugin compiled into the program is
switched by its own setting in the configuration file, which the panel edits and this command leaves alone.

The command used to be called `zettcode plugins`; that word still works for the scripts written against it, though
`zettcode --help` lists only `plugin`.

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

## Adding `@` resources

A mention provider adds a kind of `@` reference the composer can offer and the
model can resolve:

```text
from zettcode.plugin_api import Mention, MentionProvider, Plugin, PluginContext


class Tickets(MentionProvider):
    kind = "ticket"                 # unique across the application

    def candidates(self, query: str) -> list[Mention]:
        return [Mention("@ABC-123", self.kind, "ABC-123", "the open ticket")]

    def expand(self, name: str) -> str | None:
        return f"Ticket {name}" if name.startswith("ABC-") else None


class TicketsPlugin(Plugin[PluginContext]):
    name = "ticket-resources"

    def activate(self, ctx: PluginContext) -> None:
        ctx.agent.register_mention(Tickets())
```

`candidates(query)` returns the completions; `expand(name)` returns the text
the model sees, or `None` when the token is not this provider's. A provider may
override `rename(name)` to return the words the model reads in place of `@name`. `precedence` orders providers
(lower first); when two providers offer the same name, the first in that order owns its completion, expansion and rename.

## What a plugin can take part in

`Plugin` composes two groups of hooks, and a plugin overrides only the stages it
needs (the agent's group is `zettcode.engine.plugins`; the screen's is added by `TuiPlugin`; both are re-exported
by `zettcode.plugin_api`, which is what a plugin imports):

- **The agent's work** — the same lifecycle `zett-agent` extensions use: setup,
  run, turn, model, tool, compaction, and external events. A plugin can register
  tools, rewrite the messages sent to the model, transform a tool result, or
  watch a run finish.
- **The screen** — the header and the status line are each split into a left and
  a right side, and every side is drawn from the segments that registered.
- **The window and the turns** — the terminal asks for focus reports when it starts, so a plugin can be told when the
  reader steps away and when they come back; and either end of a turn of the conversation. A plugin that summarizes,
  notifies or waits for the reader to stop asking is built on these:

```python
from zettcode.plugin_api import PluginContext, TuiPlugin


class Away(TuiPlugin):
    name = "away"

    def activate(self, ctx: PluginContext) -> None:
        if ctx.tui is None:
            return
        ctx.tui.register_focus_handler(self.focused)
        ctx.tui.register_turn_start_handler(self.started)
        ctx.tui.register_turn_end_handler(self.ended)

    def focused(self, focused: bool) -> None:
        """The terminal window gained (``True``) or lost (``False``) focus."""

    def started(self) -> None:
        """A turn of the conversation is starting, before its request goes out."""

    def ended(self, completed: bool) -> None:
        """A turn of the conversation ended; ``completed`` is false for a stopped or failed one."""
```

Neither is a row and neither may consume anything: they are told, and what they do with the news is their own. A hook
is also told at a moment it must not disturb: it runs inside the request that just ended, before the shell is free
again, so work that starts a turn of its own — the `HOST_LINK` host's `prompt(...)`, or
`INBOX.deliver(..., mode="followup")` — is scheduled, not done in the handler.

What is a turn: a request the reader sent, or one another session sent and this one answered. Running a command is
not itself a turn, though a turn a command starts with `host.prompt` is; a side question and a resumed request are
not turns either. A terminal that does not report focus (``DECSET 1004``) simply never calls the first hook, and
nothing else changes.

```python
from zettcode.plugin_api import ShellContext, TuiPlugin


class WorkspaceLabel(TuiPlugin):
    """Replace the header's right segment with a model/workspace label."""

    name = "workspace-label"

    def render_header_right(self, context: ShellContext) -> str:
        return f"{context.model.name} · {context.session.workspace.name}"
```

Returning a `str`, a styled `TextLine`, a `Row`, or `None` (draw nothing). A `Row` is built from named parts (`row.add(name, summary, text)`), which `/statusline` switches; `lead`/`trail` are fixed text around them. A span with no
style of its own inherits the row's muted style, so a segment blends in by
default and opts into colour when it wants to. Registering under a name that
already exists **replaces** that segment in place; a new name is appended after
the ones already on that side. Returning `(value, True)` takes the side over
entirely, which is the way to do it without depending on the built-in names.

Before a model is configured, `context.model.name` is empty, `context.model.efforts`
is empty, and `context.model.config` — the entry itself — is `None`. A segment that
reads the entry should say it has no model rather than assume one is there.

## Off by default

A plugin chooses whether it is on when the reader has not asked. Override `default_enabled` and return `False`; the
loader leaves it out until `[plugins] enable` names its entry point:

```python
class Quiet(TuiPlugin):
    name = "quiet"

    @classmethod
    def default_enabled(cls) -> bool:
        return False
```

```toml
[plugins]
enable = ["quiet"]
```

The default is `True`, so a plugin that says nothing loads as before.

## Command-line flags

A plugin declares startup flags by overriding the class method `cli_arguments()`:

```text
CliOption(flags=("--journal-limit",), dest="limit", help="...", default="3", metavar="N")
```

The loader reads the declaration from the plugin class before it reads the
configuration, so the flags work even before a workspace is chosen. The parsed
values are the `PLUGIN_CLI` service, grouped by entry-point name:

```text
limit = ctx.service(PLUGIN_CLI, dict).get("journal", {}).get("limit", "3")
```

The flags are global, before a subcommand: `zettcode --journal-limit 5 resume ID`.
`zettcode daemon spawn` accepts the same flags and passes the values to its
child process privately. Values must be JSON-safe (`str`, number, bool, list,
dict, or `None`), because a daemon passes them through JSON. A declaration with
a colliding flag or a non-JSON default is skipped with one message, never a
traceback.

Only **entry-point** plugins can declare these flags. Their declarations are read from the plugin classes when the
cache is built; a single `.py` file has no entry point, so its `cli_arguments()` is never consulted. Refreshing the
cache imports every installed plugin class, including a disabled one — keep that module cheap to import. `zettcode --help` deliberately skips discovery and therefore does not list these flags;
`zettcode daemon spawn --help` does. `~/.zettcode/.ztrc` presets them for a session start only, not for
`daemon spawn`.

To keep the interactive start fast, the parser reads these declarations from `~/.zettcode/plugin-cli.json` instead of
importing every plugin. When the cache is missing or stale, a daemon thread imports the plugin classes and refreshes
it; the first start after installing or changing a plugin therefore has no new flags, and the next start has them.
A cache miss is accepted rather than waiting; `prompt`, `--dry-run` and `daemon spawn` refresh synchronously because
they end too soon for the background thread. If `.ztrc` names a plugin flag before the cache exists, that one start
refreshes the declarations synchronously and applies them, so the preset is not lost.

## Reading the configuration

A plugin that has settings declares them, with the value each one takes when the reader has not written one. The
configuration file cannot know which plugins are installed, so it keeps each plugin's own table as written
(`[plugins.<name>]`), and the plugin decides what the keys mean. `<name>` is the plugin's declared `name`; a plugin
published as `greeter` that declares `name = "greeting"` writes `[plugins.greeting]` but is switched off with
`disable = ["greeter"]`, because switches use the entry-point origin:

```python
def activate(self, ctx: PluginContext) -> None:
    given = ctx.settings.declare(after_seconds=180, quiet=False)
    self.after_seconds = int(given["after_seconds"])
    self.quiet = bool(given["quiet"])
```

The reader's value wins; a value that is not the default's type is refused when the plugin activates, naming the table
and the key; reading a key the plugin never declared is an error rather than a silent default. A `[plugins.recap]`
table for a plugin that is not installed is harmless, and a plugin that ships later needs no change to the
configuration code.

```toml
[plugins.recap]
after_seconds = 240
quiet = true
```

`declare` may be called more than once, with more keys: the defaults are what the reader's table is checked
against and what the values are when it says nothing.

A plugin's settings table and the `[plugins]` switches live side by side in the same file. You do not need a
`[plugins]` line of your own for `[plugins.recap]` to work, and `/plugins` and `zettcode plugin disable` write
`disable = [...]` next to it: when the file has only `[plugins.<name>]` tables, they add the `[plugins]` header at the
end of the file, below your tables, and leave everything you wrote where it is. A file that declares `plugins` another
way (an inline table, dotted keys such as `plugins.disable = []`, `[[plugins.<name>]]`, or a `[plugins.disable]`
table) is not edited; they say so and leave it to you.

## Two command systems

Use `ctx.commands` for a command whose answer is words or a document; it runs in
every front end. Use `ctx.tui` for a command that needs a terminal page, the
shell, a live row or the `CommandHost` operations.

| | `ctx.commands` | `ctx.tui` |
| --- | --- | --- |
| Handler context | `PlainCommandContext` | `CommandContext` |
| Result | `TextCommandResult` or `TurnCommandResult` | `CommandResult` |
| Works without a screen | yes | no |
| Handler | sync or async | async |
| Name | needs the leading `/` | leading `/` is optional |
| Shell access | `PlainCommandHost` (`compact`, `title`, `export`) | full `CommandHost` |
| Page/widget | no | `CommandResult.widget` |

A plain command's `host` may be `None`: the terminal adapter passes `None`,
while the server passes a real `PlainCommandHost`. Check it before using it.

`CommandHost` is the terminal command's shell API: `client`, `agent`,
`transcript`, `commands`, `prompt(text, *, shown=None, cache=None)`,
`close_page`, `request_layout`, `wait_for_frame`, `offer`, `quit`,
`select_session`, `resume_session`, `fork_session`, `rename_session`,
`run_continue`, `run_side_question`, `change_model`, `select_model`,
`change_effort` and `change_permission`. `CommandContext.require_host()` returns
it or raises `RuntimeError`. `CommandAgent` exposes `session_id`, `workspace` and
`require_session()`; `CommandTranscript` exposes `notice`, `error`, `markdown`,
`start_compaction`, `complete_compaction` and `clear`.

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

A command that waits on the model, or on anything else that takes seconds,
returns the waiting instead of doing it: `intro` says what is happening and
`run` is the rest of the result. The shell puts `intro` in the pinned row the
reader is already watching, awaits `run`, and settles the row when it answers;
Ctrl-C, Escape, the next line the reader sends, and Enter on an empty draft
stop it, and the row says `stopped`.

```python
from zettcode.plugin_api import (
    HOST_LINK,
    CommandContext,
    CommandResult,
    HostLink,
    PluginContext,
    TuiPlugin,
)


class Recap(TuiPlugin):
    name = "recap"

    def activate(self, ctx: PluginContext) -> None:
        # The shell does not exist yet; this is how a command reaches it when it runs.
        self.link = ctx.find(HOST_LINK, HostLink)
        if ctx.tui is not None:
            ctx.tui.register_command("recap", "summarise this session", self.recap)

    async def recap(self, context: CommandContext) -> CommandResult:
        return CommandResult(intro="Recap \u2026 writing", run=self.really_recap())

    async def really_recap(self) -> CommandResult:
        if self.link is None or self.link.host is None:
            raise ValueError("The shell is not ready yet")
        host = self.link.host
        answer = await host.client.session.ask("Recap where this session is, briefly.", cache="read", origin="recap")
        return CommandResult(message=f"> {answer}")
```

`ask` is a side question: the exchange never joins the conversation, and the shell draws nothing of it, because it
began no turn — that happens whatever the arguments say. `origin="recap"` is the other half: it says who asked, and a
question that is not the reader's own is left out of the transcript a resumed session rebuilds. A command that keeps the
default `origin="reader"` would find its own words back on screen after a reopen. The answer appears only where the
command puts it — here, as a quote. `/btw` is the same kind of question with the reader's origin, so the shell draws
that one, and restores it.

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
from zettcode.plugin_api import PlainCommandContext, TextCommandResult


def notes(context: PlainCommandContext) -> TextCommandResult:
    """Answer with a document, which the front end shows in a view of its own."""
    return TextCommandResult(markdown="# Notes\n\n- the build is green\n- two things to read")
```

Register it in `activate` with `ctx.commands.register("/notes", "show the notes", notes)` — a plain command needs
the leading slash. Its context has `argument`, `level` (`deny`/`ask`/`safe`/`full`) and an optional `host` with
`compact()`, `title()` and `export()`. The terminal adapter passes `host=None`; a plain command that needs one must
handle that and say which front end cannot do it. `markdown` is a field rather than a third result type, so nothing written against the older
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

A turn reads the conversation's cached prefix and, by default, extends it for the next one — that is what makes a
long conversation cheap. A command whose answer nobody will build on can say otherwise: `prompt(text, cache="read")`
reuses the warm prefix without marking this request's own words for caching, and `cache="off"` sends no cache
directive at all. A plain command says the same with `TurnCommandResult(prompt=…, cache="read")`, which every front
end that runs it honours. The default, `"read_write"`, is what a turn of the conversation should keep.

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

A name with a description is a `zettcode.plugin_api.Subcommand("prod", "the live site")`, and a
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
from zettcode.plugin_api import Plugin, PluginContext
from zettcode.plugin_api import Provider


class Acme(Plugin[PluginContext]):
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
it, and switched to with `/theme <name>`. ZettCode's own palettes (`nord`, `dracula`, `gruvbox-dark`, `gruvbox-light` and the
rest) are offered the same way by a built-in plugin, so this is the whole mechanism:

```text
from pathlib import Path

from zettcode.plugin_api import PluginContext, TuiPlugin


class Palettes(TuiPlugin):
    name = "acme-palettes"

    def activate(self, ctx: PluginContext) -> None:
        # A theme file shipped inside your package: same format as ~/.zettcode/themes/<name>.toml.
        ctx.tui.register_theme("acme", Path(__file__).parent / "acme.toml")
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
from zettcode.plugin_api import Pet
from zettcode.plugin_api import PluginContext, TuiPlugin

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
from zettcode.plugin_api import EntryKind
from zettcode.plugin_api import Presenter
from zettcode.plugin_api import PluginContext, TuiPlugin
from zettcode.plugin_api import Span, Style, TextLine


class QuietNotice(Presenter):
    def handle(self, entry, next):
        return self if entry.kind is EntryKind.NOTICE else next(entry)

    def lines(self, entry, width, theme, frame):
        return self.text_lines(entry.text, width, Style(foreground=theme.muted))


class QuietNotices(TuiPlugin):
    name = "quiet-notices"

    def activate(self, ctx: PluginContext) -> None:
        ctx.tui.register_presenter(QuietNotice())
```

A presenter's `handle(entry, next)` is its whole claim: return `self` to draw the entry, or call
`next(entry)` to pass it on. The registry only orders the chain and starts it — it never matches a
row itself. A presenter that always returns `self` takes every row it is asked about, so its place decides:
register a catch-all with a `priority` below the built-ins (`priority = -1`) to make it a fallback. The built-in `ToolPresenter` is
a fallback because it is registered before the named tool presenters.

The built-in presenters claim by `entry.kind`; the tool presenters claim by the tool's own name
(`entry.tool`), so `read` and `read_file` share a reader presenter, `glob` and `grep` share a search presenter, and each tool
family has its own; `ToolPresenter` is the fallback for any tool none of them named. A plugin can replace one
tool without touching the row of another.

`lines` receives the entry, the columns
available, the palette, and an animation step, and returns `TextLine`s; a width is a budget, so wrap
or cut. A presenter that animates reads `frame`; one that does not should give the same rows for it.

When more than one presenter could draw the same rows, the higher `priority` wins, and an equal
priority goes to the later registration. That is why the built-ins are the default: priority 0,
registered first. A plugin that wants to beat another plugin raises `priority` on its presenter's
class; drawing only one family never needs a priority, because registering it later is already the
narrower claim.

## Adding a tool to the request

The setup hook can add a tool for each request. A tool is a `zett-agent`
`AgentTool`; the plugin only decides which ones this run sees:

```python
from zett_agent.tools import tool
from zettcode.plugin_api import Plugin, PluginContext


@tool
async def word_count(text: str) -> str:
    """Count words in a string.

    Guidelines:
        - Use it when the reader asks for a word count.
    """
    return str(len(text.split()))


class Counter(Plugin[PluginContext]):
    name = "word-count"

    async def on_tool(self, context) -> None:
        context.register_tool(word_count)
```

`on_tool` runs before the request is built; a tool added here is removed again
for the next request unless the hook adds it again. Use `before_tool` to
observe a call, or `on_tool_call` middleware to replace its result.

## Handing the agent a whole extension {#extensions}

The hook methods above run inside one extension that ZettCode hosts for all plugins. A plugin that
already *is* an extension, or wraps one from `zett-agent`, can hand it over whole:

```python
from zettcode.plugin_api import Plugin, PluginContext


class Audit(Plugin[PluginContext]):
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

## Depending on another plugin {#deps}

A plugin names the plugins it needs, and ZettCode activates them first:

```python
from dataclasses import dataclass
from zettcode.plugin_api import Plugin, PluginContext


@dataclass
class Stats:
    calls: int = 0


class StatsProvider(Plugin[PluginContext]):
    name = "stats-provider"

    def activate(self, ctx: PluginContext) -> None:
        ctx.inject("stats", Stats())


class Statistics(Plugin[PluginContext]):
    name = "statistics"
    deps = ("stats-provider",)  # the provider's `name`, not its distribution

    def activate(self, ctx: PluginContext) -> None:
        stats = ctx.service("stats", Stats)
        stats.calls += 1
```

`deps` holds plugin **names**: the `name` each plugin declares, or its distribution's entry-point name when it declares
none. A plugin whose need is missing, switched off, failed to
load, or part of a cycle is left out and reported with the reason, and so is every plugin that needs it. Plugins with
no `deps` between them load in the order they were found. The name is the plugin's identity, so two plugins may not
share one. A distribution or a file cannot take an entry-point name another plugin already has either; the first one
found keeps it and the other is left out, with a line in the log.

A plugin publishes an object for the ones that need it with `ctx.inject(name, service)`. The runtime's page services
are reached through the typed readers `ctx.agent.session_store_service()`, `ctx.agent.usage_ledger_service()`,
`ctx.agent.context_report_service()` and `ctx.agent.context_page_service()`;
anything else is read with `ctx.service(name, kind)` (or `ctx.find`, which returns `None` when nobody provides it).
What the object is, and how it is used, is for the plugins involved to agree on; ZettCode only keeps the name unique
and the order right.

## Starting work when something happens {#triggers}

A trigger watches for an event (a timer, a file, a socket) and starts work no prompt asked for. A plugin registers one
with a handler, and ZettCode runs it for as long as the session is open:

```python
import asyncio
from zettcode.plugin_api import INBOX, Inbox, Plugin, PluginContext, Trigger, TriggerEvent, TriggerScope


class EveryMinute(Trigger):
    name = "every-minute"            # a lowercase letter or digit first, then lowercase letters/digits/._-, 1-64; it names the lock file
    scope = TriggerScope.MACHINE     # one on the whole machine

    async def run(self, fire):
        while True:
            await asyncio.sleep(60)
            await fire({"reason": "tick"})


class Heartbeat(Plugin[PluginContext]):
    name = "heartbeat"

    def activate(self, ctx: PluginContext) -> None:
        # Mypy rejects an abstract class as a `type[_T]`; the runtime lookup is a plain isinstance.
        queued = ctx.find(INBOX, Inbox)  # type: ignore[type-abstract]
        self._inbox = queued
        ctx.agent.register_trigger(EveryMinute(), self.on_tick)

    async def on_tick(self, event: TriggerEvent) -> None:
        if self._inbox is not None:
            self._inbox.deliver(f"tick: {event.payload['reason']}",
                                mode="followup", origin="trigger")
```

`scope` says how many copies run:

- `TriggerScope.PROCESS` (the default) -- one per process. A second runtime in the same process does not start it.
- `TriggerScope.MACHINE` -- one on the whole machine, however many ZettCode windows are open. The window that holds a
  lock on a file beside the session store (`~/.zettcode/triggers/<name>.lock`) runs it; the others stand by and take
  over within a few seconds when it closes. The operating system releases the lock when its holder dies, so a window
  that crashed never blocks the trigger.

A trigger that raises is marked failed and is not restarted; a handler that raises costs only that event. Two plugins
cannot register the same trigger name.

A trigger only reports that something happened. To make the agent act on it, hand the event to the session's queue:
the `INBOX` service, whose type `Inbox` and item type `Waiting` both come from `zettcode.plugin_api`, as the handler
above does. `mode="followup"` is the polite choice for work nobody is waiting on: it never interrupts a request in
flight.

A plugin that opens something longer-lived than a turn — a connection, a background worker — releases it in
`async def aclose(self)`. The runtime calls it when the session closes, newest plugin first.

## Plugin API reference

This is the compact lookup table. The sections above explain when to use each
piece; this section is for the exact name, type and default.

### `Plugin` and `TuiPlugin`

| Member | Meaning |
| --- | --- |
| `name` | identity used by `deps`, diagnostics and `/plugins`. Empty means the entry-point name is used. |
| `origin` | entry-point name, or the file stem for a single-file plugin; set by the loader. What `[plugins] disable` and the switch file match. |
| `description` | one line declared for authors and diagnostics; the program does not display it yet. |
| `deps` | other plugin **names** this one needs; the loader activates them first. |
| `priority` | order among plugins inside the host; lower runs first. The host adopts the lowest, so one plugin’s priority moves the whole bundle against other extensions. Default `100`. |
| `setting` | program-only: the config key that switches a compiled-in plugin; a third-party plugin declares none. |
| `rank` | program-only ordering inside a role group; a third-party plugin leaves it at `0`. |
| `default_enabled()` | class method; return `False` to require `[plugins] enable = ["name"]`. |
| `cli_arguments()` | class method; returns `CliOption` declarations for startup and `daemon spawn`. |
| `activate(ctx)` | synchronous; register everything the plugin contributes. |
| `aclose()` | async; release long-lived resources, once, in reverse activation order. |

`TuiPlugin` is `Plugin` plus four optional row methods:
`render_header_left`, `render_header_right`, `render_status_left`,
`render_status_right`. Each receives `ShellContext` and returns a segment,
`None`, or `(segment, True)` to take that side over.

### Agent hook groups

A plugin can override only the stages it needs. All are async except `accept`, and default to
doing nothing:

| Group | Methods |
| --- | --- |
| setup | `on_tool`, `on_state`, `on_message` |
| run | `before_run`, `after_run`, `on_success`, `on_error` |
| turn | `before_turn`, `after_turn` |
| model | `before_model`, `after_model` |
| tool | `before_tool`, `after_tool` |
| maintenance | `on_compact` |
| events | `accept(config, event) -> bool`, `on_event` |
| middleware | `on_model_request`, `on_tool_call` |

The hook signature and the mutable context come from `zett-agent`. A plugin
that already is an extension can be registered whole with
`ctx.agent.register_extension()`; `register_extension_factory(name, build)`
defers the import/build until the agent is built.

### Context methods

| Method | Contract |
| --- | --- |
| `service(name, kind)` | required; `LookupError` if absent, `TypeError` if the type is wrong |
| `find(name, kind)` | optional; `None` instead of raising |
| `provide(name, value)` / `inject` | publish for later plugins; the name must be unique and not one of the six `PLUGIN_*` names |
| `register_provider(Provider)` | add a model host to `/config` |
| `register_extension(AgentExtension)` | hand the agent a whole extension |
| `register_extension_factory(name, build)` | build it later; `build` may return `None` |
| `register_mention(MentionProvider)` | add an `@` resource kind |
| `register_trigger(Trigger, handler)` | start a long-running watcher with the session |

### Commands

`ctx.commands.register(name, summary, handler, *, when_busy="refuse", subcommands=())`
adds a plain command. The handler receives `PlainCommandContext`:

| Field | Meaning |
| --- | --- |
| `argument` | raw trimmed text after the command name |
| `level` | `deny`, `ask`, `safe` or `full` |
| `host` | `PlainCommandHost \| None`; use it for `compact`, `title`, `export` |

`TextCommandResult(message="", notification="", markdown="")` answers with words,
a toast or a document. `TurnCommandResult(prompt, shown="", notification="",
cache="")` starts a conversation turn; `cache` is `"read"`, `"read_write"` or
`"off"`.

`ctx.tui.register_command(name, description, handler, *, when_busy="refuse",
subcommands=())` adds a terminal command. Its handler receives `CommandContext`
with `argument`, `ui` and `host`; `context.require_host()` is the shell. The
`CommandResult` fields are `message`, `notification`, `widget`, `relayout`,
`intro` and `run`. `intro` plus `run` keeps a slow command's row alive.

`when_busy` is one of:

- `"refuse"` (default): turned away while a request runs.
- `"queue"`: held until that request ends.
- `"now"`: runs beside the request; only for reads or settings the request
  reads when it needs them.

### Screen contributions

`ctx.tui` is `None` without a terminal. The methods are:

| Method | What it adds |
| --- | --- |
| `register_command` | a `/command` with a `CommandUi` and `CommandHost` |
| `register_header_left/right`, `register_status_left/right` | a segment (`str`, `TextLine` or `Row`); a blank `name` appends (`segment-N`), while a `render_*` override registers `<region>_<side>` and replaces the built-in; `override=True` clears that side |
| `register_turn_segment(name, summary, builder)` | an item of the line a request ends on; name starts `turn-` |
| `register_theme(name, theme, *, description="")` | a palette, file, or builder |
| `register_pet(name, pet, *, description="")` | a pet, or a builder |
| `register_presenter(presenter)` | a row presenter; later registration wins ties |
| `register_focus_handler(handler)` | window focus gained/lost |
| `register_turn_start_handler(handler)` | a turn starts |
| `register_turn_end_handler(handler)` | a turn ends; `completed` is false if stopped/failed |

`register_turn_segment` requires a name starting with `turn-`; the builder receives
`TurnContext(label, seconds, clock, usage, tools, failed_tools)`, and the
`[statusline]` switch for that name hides it. A row method receives `ShellContext`:

| `ShellContext` field | Type | What it holds |
| --- | --- | --- |
| `config` | `ZettCodeConfig` | resolved configuration |
| `session` | `SessionState` | `id`, `title`, `name`, `workspace`, `handle` |
| `model` | `ModelState` | `config`, `name`, `effort`, `efforts` |
| `activity` | `ActivityState` | `busy`, `status`, `note`, `auto_shell`, `usage`, `tasks`, `frame`, `permission`, `self_compact` |
| `display` | `DisplayState` | `theme`, `width`, `height`, `screen`, `scrolled_up` |

A presenter implements `handle(entry, next)` and `lines(entry, width, theme,
frame)`. `handle` returns `self` to claim the entry or `next(entry)` to pass it
on. `priority` breaks ties; `gutter` asks for the marker column; `look` names
the fields the rendered block depends on; `block` caches the rendered lines;
`text_lines` wraps and indents text to the width. Entries expose `id`, `kind`
(`EntryKind`), and type-specific fields such as `text`, `tool`, `title` and
`diff`; `EntryStatus` is `running`/`completed`/`failed`/`skipped`.

### Settings and CLI flags

`ctx.settings.declare(**defaults)` returns the reader's values, or the defaults.
It may be called more than once, with more keys; `ctx.settings.get(key)` reads
one declared key and `ctx.settings.values()` returns all of them. Only `bool`,
`int`, `float` and `str` are allowed. The reader writes `[plugins.<name>]`; a
wrong type is refused at activation with the key named.

`cli_arguments()` returns `CliOption(flags, dest, help="", default=None,
action="store", choices=None, metavar=None)`. The parsed values are
`ctx.service(PLUGIN_CLI, dict).get(origin, {}).get(dest)`. Flags belong before a
subcommand: `zettcode --journal-limit 5 resume ID`. `daemon spawn` accepts the
same flags and passes the values to its child privately. A bad option is
skipped with one message; it does not stop ZettCode.

### Loading, ordering and failure

- `deps` names plugins, not distributions; a missing, disabled, failed or cyclic
  dependency leaves the dependent plugin out and reports why.
- A plugin whose `default_enabled()` is false loads only when `[plugins]
  enable` names it, the program requires it, or a kept plugin needs it.
- Duplicate identities, command names claimed by another plugin, service names, extension names, theme names and pet
  names fail the later plugin, not the whole application.
- a process with no screen: `ctx.tui is None`; a plugin must guard screen-only
  work.
- `Plugins.failures` has `origin: why`; `Plugins.taken` records a name lost to
  an earlier plugin. A failed plugin provides nothing.
- `aclose` runs newest first. A failure is logged and does not stop the others.

## Testing a plugin

A plugin is ordinary Python. Build a context with the test helpers and call
`activate` yourself; no terminal is needed:

```python
from zettcode.app.plugins.loader import terminal_context
from zettcode.config import ModelConfig, ZettCodeConfig
from zettcode.plugin_api import PLUGIN_CLI


def activate_for_test(tmp_path):
    config = ZettCodeConfig(
        workspace=tmp_path,
        store=tmp_path / "sessions",
        models=(ModelConfig(model="example", token="test"),),
    )
    ctx = terminal_context(config, {PLUGIN_CLI: {"journal": {"limit": "5"}}}, name="journal")
    Journal().activate(ctx)
    return ctx
```

Use `PluginContext(config, services)` and `ctx.commands` when the plugin has no
screen half. Screen tests need the program installed (`zettcode.app` is not a
dependency of `zettcode-plugin-api`); a plugin with no screen half needs only
`PluginContext`. Test command handlers by constructing
`PlainCommandContext(argument="...")` or `CommandContext(argument="...",
ui=... )`; test screen contributions through `ctx.tui` and the same context
helpers the application uses. Keep tests in temporary directories: a plugin
must never write the reader's home or the checkout.

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
  enabled`, `[agents_md] enabled`, `[harness] subagent`, `[harness] todowrite`, `[harness] jit`,
  `[compaction] self`, `[ask_user] enabled` — and the page
  writes that key in your config file. A compiled-in plugin with no such setting is not on the page at all: there would
  be nothing to press. (One that failed to load is still listed, for its reason — that is worth knowing even with
  nothing to press.)
- The program's own **terminal parts** that are not required (`themes`, `pets`, `context`, `usage`) are listed as
  third-party rows and `[plugins] disable` reaches them. The four the terminal cannot start without are hidden, and
  `zettcode plugin disable` does not reach either group.

A plugin that wanted a name another plugin already had is listed with a note and no switch: the one that loaded keeps
the name, and the page says which one lost it rather than leaving the loss in a log.

A name in `[plugins] disable` can be switched back on from the page: it is an ordinary switch now, not a line held back
for the reader. The question has one answer wherever it is asked: the terminal's `/plugins` page, the editor's
**ZettCode: Show Plugins** panel and `PUT /plugins/{name}` on the server go through the same rules and write the same
files.

## When something goes wrong

A plugin that cannot be imported or activated is reported, not fatal. Where the failure lands depends on what
failed:

| Failure | What happens |
| --- | --- |
| import, `activate`, duplicate identity, or a name clash (a command another plugin claimed, theme, pet, provider, mention, extension, trigger, service) | the whole plugin is rejected and none of its registrations survive; `origin: why` appears in the transcript and `Plugins.failures` |
| a dependency missing, disabled, failed or cyclic | the dependent plugin is rejected too, with `needs plugin 'x' …` |
| a command raises `ValueError` or `ZettCodeError` | the shell shows that sentence as the command's own error |
| any other command exception | one `/<name>: <reason>` line, and the traceback is logged |
| a focus / turn-start / turn-end handler raises | one `a plugin hook failed: …` line, reported once; the handler is still called on later events. An agent-side hook (`before_turn`, `on_tool`, …) failing propagates and fails the request instead |
| a trigger raises | the trigger is marked failed and is not restarted; a handler that raises costs one event |
| a presenter raises while painting | it is not isolated like a hook: return the same rows for every frame and do not raise |

A failed plugin provides nothing. `ctx.find` returns `None`; `ctx.service` raises `LookupError`. The same facts
are in the shell's `plugin: …` line, `/plugins`, and `client.plugins.failures` on an SDK client; `plugin list` shows
installation and switch state, not failure reasons. Structured logs are JSON lines under `~/.zettcode/log/` (`terminal.jsonl` by default); set
`ZETTCODE_LOG_LEVEL=debug` for more. `Plugins.taken`
records a name lost to an earlier plugin. Two plugins may not share an identity; the first keeps it. Command names
are also shared. A name held by the shell's four commands (`/config`, `/theme`, `/pet`, `/statusline`) or the agent's
commands (`/new`, `/compact`, `/export`) is silently dropped: the plugin loads, its command is not listed and cannot be
run, and no failure is reported; check `/help` after installing. A name held by another plugin — including a program
plugin such as `/model` or `/resume` — makes the plugin fail to load with "command … is already registered by another
plugin", and that appears in `Plugins.failures`.
