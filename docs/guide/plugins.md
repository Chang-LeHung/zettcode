# Plugins

A plugin is a Python package that adds something to ZettCode: a command, a tool, a row on the screen, a model host, a
palette, a pet, or work that starts on a timer. Installing the distribution is the opt-in — there is no registry to
edit.

## Install one

```sh
zettcode plugin install owner/repo                 # a GitHub repository, at a tag, branch or commit
zettcode plugin install /path/to/greeter           # a local project, wheel or sdist
zettcode plugin install ./greeter.py               # a single Python file
```

The package goes into the environment `zettcode` runs in; its commands appear after a restart. A single `.py` file is
copied to `~/.zettcode/plugins` instead, where every start loads the `Plugin` classes it defines: one module, no
relative imports, and `--force` to replace a file whose content differs. By hand, the same install is
`uv tool install --force --with /path/to/greeter zettcode`, or `pip install /path/to/greeter` in the environment
ZettCode runs in.

`zettcode plugin list` shows each plugin's origin, location and switch; `--json` is the same for a program.
`zettcode plugin uninstall <name>` removes a single file or a distribution.

::: warning Install only trusted plugins
Plugins run Python inside the ZettCode process and can change both the model's work and your files. They are not
sandboxed: read the source before you install it.
:::

## What this repository publishes

| Package | Adds | Install with |
| --- | --- | --- |
| `zettcode-models` | An official model for each vendor key in the environment: OpenAI, Anthropic, DeepSeek, Z.AI | `zettcode[models]` |
| `zettcode-recap` | `/recap`: a summary of where the session is, for when you step away | `zettcode[recap]` |
| `zettcode-monitor` | `/monitor`: every model call and its answer, exported as HTML, unredacted | `zettcode[monitor]` |
| `zettcode-code-agents` | Codex and Claude Code as members of sessions and groups | `zettcode[code-agents]` |

`zettcode[all]` installs all four; the last is a gateway plugin and adds nothing to the terminal.

`/monitor` is the one with a panel of its own: two switches for this session — record its model calls, and keep the
image data in them — and a row that writes everything recorded so far into an HTML file in the workspace, unredacted.

![The /monitor panel: a switch for recording, a switch for keeping images, and the row that writes the report](/screens/monitor.svg)

`←` `→` move a switch but change nothing yet; `Enter` saves both and closes, on the Export row it writes the file
first, and `Esc` closes without applying anything. A report with nothing in it keeps the panel open and says why.

## Turn one off or on

`/plugins` opens a page with a switch for each plugin you can switch: Space flips one, Enter writes, Escape writes
nothing. `zettcode plugin enable <name>` and `zettcode plugin disable <name>` do the same for one name, and `/plugins
disable <name>` does it from the composer. Every switch takes effect at the **next start**.

![The /plugins page: the program's own plugins first, then installed ones, each row with its switch, the key or distribution the switch writes, and what the plugin adds](/screens/plugins.svg)

The row says which side of that line a switch falls on: a compiled-in plugin is switched by a configuration key
(`rows.enabled`), an installed one by `[plugins] disable`. A plugin that could not load keeps its row — that is how you
find out — and one whose setting this process never read has no switch at all, with the reason on the line under the
list.

```toml
[plugins]
enabled = true          # false leaves every third-party plugin out; the built-in screen stays
disable = ["recap"]     # installed plugins left out at the next start
enable = ["quiet"]      # a plugin that declares itself off by default
```

`disable` and `enable` name the plugin's **origin** — its entry-point name, which can differ from the package name and
from the plugin's own `name`. A plugin compiled into the program is switched by the setting it already has (`[mcp]
enabled`, `[skills] enabled`), and the page writes that key instead. The terminal parts the screen cannot start without
are not on the page at all.

## Where a plugin's settings live

Settings are a `[plugins.<name>]` table in `config.toml`, beside the switches. The plugin declares each key with the
value it takes when you write none:

```toml
[plugins.recap]
after_seconds = 240
```

`<name>` is the plugin's own name, not its origin. A value of the wrong type is refused when the plugin activates, and
the message names the table and the key. You need no `[plugins]` line of your own: `/plugins` adds the header below your
tables and leaves them as they are.

## What plugins can add

### Models from a provider {#providers}

A host whose models appear in `/model` without being written to `config.toml`, and a token read from the environment.
Detail: [Offering models at a provider](/guide/plugin-api#providers).

### Official models from your environment {#official-models}

`zettcode[models]` registers one current official model per vendor key it finds, and a machine with no model configured
starts on it. Detail: [official models](/guide/plugin-api#official-models).

### Palettes and pets

`/theme` and `/pet` draw from plugins too, so a plugin can ship a palette or a pet; the built-in ones are offered the
same way. Detail: [palettes](/guide/plugin-api#themes) and [pets](/guide/plugin-api#pets).

### Commands, rows, tools and triggers

A plain `/command` that works in every front end, a terminal command with a page of its own, a row in the transcript, a
tool in the request, and work that starts on a timer. Start at
[writing a command](/guide/plugin-api#writing-a-command).

## When a plugin will not load {#when-something-goes-wrong}

A plugin that cannot be imported or activated is reported as `plugin: …`, and the rest of the program keeps working. A
name already taken is the usual cause: a command the shell owns is dropped without a word, and one another plugin owns
fails the plugin. `/plugins` and `zettcode plugin list` show which plugin and where it stands; the
[reference](/guide/plugin-api#when-something-goes-wrong) has the table of every failure and how to see it.

## Writing one

A plugin is a `Plugin` subclass whose `activate(ctx)` registers what it adds, plus one entry point in its
`pyproject.toml`; `zettcode-plugin-api` is its only dependency. [The plugin API](/guide/plugin-api) has a complete
example, every registration, the reference tables and the test helpers.

## Next steps

- [The plugin API](/guide/plugin-api): write, test and register a plugin.
- [Skills and MCP](/guide/skills-and-mcp): tools and instructions without writing code.
- [Commands](/guide/commands): the built-in commands, and where a plugin's name goes.
