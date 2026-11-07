# Splitting `zettcode` into namespace packages

Status: **stages 1–4 landed**, stage 5 is the release and the documents that describe it (this file among them).
This is the contract for the migration: the target shape, who owns every module, and the order the work lands in.
Each stage ended green — `make check` plus the plugin suites — and was committed on its own, so a stage that went
wrong could be reverted without taking the rest with it.

## Why

Two goals, and the second is what fixes the shape:

1. The program is one distribution today. Its parts have different audiences and different dependency weights: the
   TUI framework is a widget library, the engine is a runtime over `zett-agent`, the server and the gateway are faces
   of it.
2. A plugin should have **one** package to depend on. Today a plugin imports `zettcode.app.plugins`, `zettcode.tui`,
   `zettcode.config` and `zettcode.engine`, so `pip install zettcode` is its only option — the whole program, with
   every face and every UI widget.

The engine has no dependencies of ours, so it is the root of the dependency graph: everything else may depend on it,
it depends on nothing but `zett-agent` and `pydantic`. A plugin that adds an agent extension needs that and nothing
more; a plugin that draws needs the TUI side too, which is why `zettcode-plugin-api` exists (below).

## The namespace

`zettcode` becomes a **PEP 420 namespace**: no distribution ships `zettcode/__init__.py`, so the namespace is the
union of what is installed and every distribution contributes its own parts to it. Consequences, accepted:

- `import zettcode` gives an empty namespace module. The facade it used to be (`ZettCodeConfig`, `ZettCodeEngine`,
  `ZettCodeAgent` by lazy `__getattr__`) goes away; the names are imported from the package that owns them
  (`from zettcode.engine import ZettCodeConfig, ZettCodeEngine`, `from zettcode.sdk import ...`).
- `zettcode.__version__` goes away. Each distribution has its own `__version__`, in its own `__init__.py`, and its own
  `<name>-v<version>` tag — the release workflow in `.github/workflows/release-packages.yml` already publishes by
  version-vs-PyPI, so it releases these the moment they exist under `packages/`.
- A distribution may ship *any* path under the namespace, so module paths do not have to be renamed when ownership
  moves: `zettcode.config` can be shipped by `zettcode-engine` and imported by everything above it. **No import
  statement changes because a file changed wheels.**

## The distributions

| Distribution | Ships | Depends on |
| --- | --- | --- |
| `zettcode-engine` | `zettcode/engine/**`, and the leaves the runtime needs: `config`, `config_edit`, `paths`, `providers`, `prompt`, `relay` (the marker), `wire`, `wording`, `filelock`, `error_text`, `budget`, `modes`, `logging_setup`, `processes`, `registry`, `statusline_parts`, `_compat`, `plugin_tui`, `mention` (the protocol and the registry), `version` | `zett-agent`, `pydantic` |
| `zettcode-tui` | `zettcode/tui/**` and a local `tui/_compat.py` | — (no distribution of ours) |
| `zettcode-broker` | `zettcode/broker/**` | `zettcode-engine` (filelock, logging_setup, modes, processes) |
| `zettcode-sdk` | `zettcode/sdk/**`, `zettcode/daemon/**`, `zettcode/doctor.py`, `zettcode/mentions.py` (the implementations), `zettcode/table.py`, and the composition root `zettcode/sdk/builtins.py` | `zettcode-engine`, `zettcode-broker` |
| `zettcode-server` | `zettcode/server/**` | `zettcode-engine`, `zettcode-sdk` |
| `zettcode-gateway` | `zettcode/gateway/**` | `zettcode-engine`, `zettcode-sdk` |
| `zettcode-plugin-api` | `zettcode/plugin_api/**`: the plugin contract — `Plugin`/`TuiPlugin` and the row hooks (`mixins`, `plugin`, `state`, `rows`), commands (`commands`), the row model and the presenter base class and registry (`entries`, `presenters`), the pet format (`pets`), the link to the shell (`host`), and the widgets a panel is drawn with (`panels`, `switch`) | `zettcode-engine`, `zettcode-tui` (and `zettcode-sdk` only through the `types` extra, to type-check a plugin) |
| `zettcode-presenters` | `zettcode/presenters/**`: the built-in rows — the presenters of every kind of entry, their wording (`text`), the pulse (`pulse`) and the brand mark (`brand`) | `zettcode-plugin-api`, `zettcode-tui`, `zettcode-sdk` |
| `zettcode-commands` | `zettcode/commands/**`: the slash commands that act on the application (`/help`, `/plugins`, `/resume`, `/model`, `/btw`, `/code-review`, `/bash`, `/clear`, `/usage`) as the one plugin `commands`, which the terminal requires; the pages they open are the application's widgets, so it sits above `zettcode-app` | `zettcode-app`, `zettcode-plugin-api`, `zettcode-engine`, `zettcode-tui`, `zettcode-sdk` |
| `zettcode-pets` | `zettcode/pets/**`: the thirteen pets that ship and `PetsPlugin`, which offers them to `/pet`; found through the `zettcode.plugin` entry point, not required | `zettcode-plugin-api` |
| `zettcode-skills` | `zettcode/skills/**`: the `@` provider for skills (`SkillMentions`) and the plugins `skills` and `skill-tool`; found through the `zettcode.plugin` entry point, switched off by `[skills] enabled`; the SDK and `zettcode` depend on it | `zettcode-engine` |
| `zettcode-files` | `zettcode/files/**`: the `@` provider for the workspace's files (`FileMentions`) and the plugin `files`, which nothing turns off; found through the `zettcode.plugin` entry point; the SDK and `zettcode` depend on it | `zettcode-engine` |
| `zettcode-jit-harness` | `zettcode/jit_harness/**`: the switchable just-in-time harness (`SwitchedHarness`, imported only when the agent is built), the plugin `harness`, and — because the part owns them — the `/harness` command and the panel it opens (`command`, `page`, the command registered only where there is a screen); found through the `zettcode.plugin` entry point, switched by `[harness] jit`; the SDK and `zettcode` depend on it. The runtime keeps the switch (`HarnessSwitch`) and the paths in the engine, since the session folders reach them without the part | `zettcode-engine`, `zettcode-tui`, `zettcode-plugin-api`, `zett-agent` |
| `zettcode-mcp` | `zettcode/mcp/**`: the MCP extension that says what its servers do (`extension`, imported only when the agent is built) and the plugin `mcp`; found through the `zettcode.plugin` entry point, switched off by `[mcp] enabled`; the SDK and `zettcode` depend on it | `zettcode-engine` |
| `zettcode-messaging` | `zettcode/messaging/**`: the line to the other sessions (`messenger`), the four tools a model reaches them with — `list_sessions`, `send_message`, `message_history`, `manage_group` (`extension`) — and the plugin `messaging`; found through the `zettcode.plugin` entry point, and the shell and the SDK both depend on it. It is the only distribution of the agent's parts that depends on `zettcode-broker` | `zettcode-engine`, `zettcode-broker`, `zett-agent` |
| `zettcode-ask-user` | `zettcode/ask_user/**`: the plugin `ask-user`, which hands the agent the framework's `ask_user` tool (imported only when the agent is built); found through the `zettcode.plugin` entry point, switched off by `[ask_user] enabled`; the SDK and `zettcode` depend on it | `zettcode-engine`, `zett-agent` |
| `zettcode-instructions` | `zettcode/instructions/**`: the plugin `project-instructions`, which hands the agent the workspace's `AGENTS.md` files as it reads them for every request; found through the `zettcode.plugin` entry point, switched off by `[agents_md] enabled`; the SDK and `zettcode` depend on it | `zettcode-engine`, `zett-agent` |
| `zettcode-todos` | `zettcode/todos/**`: the plugin `todos`, which provides the plan as a service and hands the agent the `todo_write` tool when the tool is on; found through the `zettcode.plugin` entry point, switched by `[harness] todowrite`; the SDK and `zettcode` depend on it | `zettcode-engine`, `zett-agent` |
| `zettcode-tool-output` | `zettcode/tool_output/**`: the plugin `tool-output`, which moves a `bash` command's kept streams out of the reader's project and into the session's folder (`tool-output/`), with the extension it hands the agent (`extension`, over the store the runtime provides); found through the `zettcode.plugin` entry point and nothing turns it off; the SDK and `zettcode` depend on it | `zettcode-engine`, `zett-agent` |
| `zettcode-truncation` | `zettcode/truncation/**`: the plugin `long-output`, the backstop for a result no tool of ours bounded — it keeps the whole result in the session's folder and sends its start and its end; found through the `zettcode.plugin` entry point and nothing turns it off; the SDK and `zettcode` depend on it. The folder's name is the engine's (`storage.KEPT_OUTPUT`), so the two parts write to one place without importing each other | `zettcode-engine`, `zett-agent` |
| `zettcode-guidance` | `zettcode/guidance/**`: the plugin `tool-guidelines`, which registers the per-tool guidance extension as a factory, so a tool's call shapes, guidelines and return type are in its own description; found through the `zettcode.plugin` entry point and nothing turns it off; the SDK and `zettcode` depend on it. The extension stays in the engine (`engine/extensions/guidance.py`), because the `task` tool builds every child agent with it | `zettcode-engine`, `zett-agent` (the type the factory returns, imported by the type checker) |
| `zettcode-app` | `zettcode/app/**`, `zettcode/collector.py`, `zettcode/statusline.py` (the rendering half), `zettcode/update.py` | `zettcode-engine`, `zettcode-tui`, `zettcode-sdk`, `zettcode-broker`, `zettcode-plugin-api`, `zettcode-presenters` |
| `zettcode` | `zettcode/cli.py`, `plugin_cli.py`, `oneshot.py`, the console scripts | all of the above |

The plugins are distributions too, and they ship inside the same namespace: `zettcode-monitor` puts its module at
`zettcode/monitor/` and `zettcode-recap` at `zettcode/recap/`, so no distribution has a top-level import root of
its own. A test holds that: `test_every_distribution_ships_under_the_zettcode_namespace`.

`zettcode` stays the distribution a reader installs: it keeps both console scripts (the rules for that are in
`AGENTS.md`) and depends on the server, so one `pip install zettcode` is unchanged in effect.

`zettcode-broker` needs four leaf modules that live in the engine package. That edge is accepted: the alternative is a
`zettcode-base` package between them, which would put a second dependency back in front of a plugin.

## Who owns the loose modules

| Module | Owner | Why |
| --- | --- | --- |
| `_compat` | engine | `StrEnum`/`tomllib`; the engine's storage and permission use it. `tui` ships a copy of the shim it needs (`tui/_compat.py`), so the framework depends on nothing of ours — only `wcwidth`, `pyperclip`, and `tomli` on 3.10. |
| `budget`, `error_text`, `filelock`, `logging_setup`, `modes`, `paths`, `processes`, `prompt`, `providers`, `wording`, `config`, `config_edit` | engine | Leaves with no dependency of ours; the runtime or its settings need them, and everything above imports them from here rather than re-owning them. |
| `plugin_tui` | engine | The `TuiGroup` ABC the engine's plugin context names; the terminal implements it. It is also the first thing `zettcode-plugin-api` re-exports. |
| `mentions` | split: the protocol and the registry in engine (`zettcode/mention.py`), `SessionMentions` in sdk, `FileMentions` in `zettcode-files`, `SkillMentions` in `zettcode-skills` | The engine needs the type and the registry that collects it (`prompt.py` takes one); the implementations read the workspace and the broker. |
| `relay` | `Relayed`, `relay_of` and the batch helpers in `zettcode-messaging` (`relayed.py`); the roster shape (`RosterPeer`) is the engine leaf in `zettcode/wire.py`, inherited by the broker's entry and the SDK's `Peer`; `RELAY` and `relay_sender` stay in the engine (`zettcode/relay.py`) | The session message is the messaging part's; the engine keeps only the stored attribute's name and a reader an export uses. |
| `statusline` | split: `NAMES`/`TURN_PREFIX` in engine, the rendering in app | `config.py` validates the `[statusline]` table and must not import the statusline's sdk and tui edges. |
| `collector` | app | The terminal's collector policy. |
| `doctor` | sdk | It runs model checks through the SDK. |
| `registry` | engine | The ordered registry the `@` resources and the shell's commands are both built on; the mention registry over it is the engine's too. |
| `table` | sdk | The daemon's output and the program's. |
| `update` | app | The release check and its page are one feature; the program's `zettcode update` command imports it. |
| `cli`, `plugin_cli`, `oneshot` | program | The console scripts. |

## What leaves the engine

The engine keeps the runtime: dialogue, storage, permission, tools, the extension machinery, the plugin machinery and
their data types. What is *composition* or *config-file writing* moves up, because it needs a broker, a config file or
a third-party library the engine must not carry:

| Today | Moves to | Because |
| --- | --- | --- |
| `engine/plugins/builtin_agent.py` (`AGENT_PLUGINS`) | `zettcode/sdk/builtins.py` | It composes the tools, storage, usage, permission, compaction, MCP, messaging and mention plugins. The server needs it too, so the SDK — not the app — is its home. |
| `engine/messenger.py` | `zettcode/messaging/messenger.py` (distribution `zettcode-messaging`) | It speaks to the broker (httpx/websockets). `ZettCodeEngine` no longer creates one, carries one, or names one: the `messaging` plugin builds it from the configuration, provides it under `SESSION_LINK`, and closes it; a front end that wants its own hands one over through `preview(shared=...)`. |
| `engine/extensions/messaging.py` | `zettcode/messaging/extension.py` (distribution `zettcode-messaging`) | Broker client and modes. |
| `engine/extensions/context.py` | `zettcode/sdk/extensions/context.py` | `tiktoken`, which the engine must not carry. |
| `engine/extensions/mcp.py` | `zettcode/mcp/extension.py` (distribution `zettcode-mcp`) | The MCP client and its config. |
| `engine/extensions/tool_output.py` | `zettcode/tool_output/extension.py` (distribution `zettcode-tool-output`) | The part that acts on the `bash` tool's result and reads the session store; a feature of the agent, not of the runtime, and the runtime needs neither to run a turn. |
| `engine/extensions/truncation.py` | `zettcode/truncation/extension.py` (distribution `zettcode-truncation`) | The same: it keeps a result no tool of ours bounded in the session's folder, over the store the runtime provides. The folder's name moved down to `engine/storage.py` (`KEPT_OUTPUT`) so the two parts read one constant instead of importing each other. |
| `engine/plugins/loader.py`'s default `builtins=AGENT_PLUGINS` | removed | The engine cannot reach the SDK; the loader takes `builtins` from its caller. |

`engine/plugins/switches.py` stays: it needs `config`, `config_edit`, `paths` and `filelock`, which the engine ships.

## The cycle to break before anything is declared

`sdk` lists and starts daemons, and `daemon` runs sessions through the SDK. A distribution cannot depend on itself
through another, so the two become **one distribution**, `zettcode-sdk`, with `zettcode/daemon/**` inside it. The
module paths stay (`zettcode.daemon` is a subpackage of the SDK's wheel).

## Stages

Each stage is one branch and one commit, and ends with `make check` green plus both plugin suites.

1. **Engine boundary, inside today's tree.** *Done.* `builtin_agent`, `messenger` and `extensions/{messaging,mcp}`
   moved to `zettcode/sdk/`; `ZettCodeEngine.preview` takes the messenger the caller built and loads no built-in
   plugin of its own; the loader requires `builtins`. `extensions/context` stayed: its report types (`ContextReport`,
   `Tokenizer`) are what the runtime's own `tokenizer` field and `context` property are, so it moves when the runtime
   stops building a tokenizer — stage 2.
2. **Split the shared modules.** *Done, with one variation.* The engine owns the data half of each and the module
   above re-exports it, so no importer changed: `zettcode/statusline_parts.py` (the names `[statusline]` may set, which
   `config.py` validates) is imported by `zettcode/statusline.py`, which paints them; `zettcode/mention.py` holds the
   token, `Mention`, `MentionProvider` and `MentionRegistry`, and `zettcode/mentions.py` keeps the implementations;
   `zettcode/relay.py` became the engine's whole (the message type and the wire vocabulary moved into it and
   `broker/protocol.py` imports them), with `zettcode/wire.py` holding the two facts the broker shares without the
   agent runtime. `test_structure.py`'s import-closure check now finds zero engine files importing something the
   engine would not ship.
3. **The namespace and the wheels.** *Done.* `zettcode/__init__.py` is gone; every distribution is a directory under
   `packages/` with a `pyproject.toml` and a wheel, each subpackage has a `py.typed`, and all of them read the one
   version file in the engine's tree. The suite moved to `tests/` inside each distribution (with the shared conftest and
   fakes in `support/`), `mypy` names every `src` tree as a package base, and the
   157 relative imports that climbed to the namespace root are absolute.
4. **`zettcode-plugin-api`.** *Done.* Both plugins depend on it and import only from it, and
   `test_a_plugin_depends_on_one_package_of_ours_and_imports_from_it` holds both halves. It began as a thin re-export of
   the application; step 6 turned it into the contract those names are defined in.
5. **Releases, packaging and docs.** *Done.* `.github/scripts/release_order.py` generates the dependency order
   `make build` and `release.yml` publish in (`make order` writes it out); `release.yml` builds and publishes every distribution under one `v<version>` tag, and
   `release-packages.yml` keeps the plugins on their own; `make smoke` builds and installs the whole set; the guide
   names `zettcode.plugin_api`, and the invariants (P3–P6) pin the engine's closure, the plugin's one dependency, the
   release order and the one version file.

6. **The contract moves down, the implementations stay up.** *Done.* `zettcode-plugin-api` used to *re-export* the
   application, so a plugin that wanted `Presenter` installed the whole terminal and `zettcode-presenters` could not
   exist without importing the application it was meant to be drawn by. It now *defines* the contract and depends on the
   engine and the widget framework only; `zettcode-presenters` (the built-in rows) and `zettcode-app` are
   written against it:

   ```
   engine   tui   sdk
        \   |   /
       plugin-api            the contract: what a plugin implements and returns
            |
        presenters           an implementation of one family of it (the built-in rows)
            |
           app               the shell, the loader, the other built-in plugins
   ```

   What moved, and why each piece is a contract rather than an implementation:

   | Moved to `plugin-api` | Why it is the contract |
   | --- | --- |
   | `commands`, `state`, `mixins`, `plugin`, `rows` | The command a handler returns, the context a row hook receives, the hooks themselves and the `Row` a segment may hand over: the types in a plugin's signatures. `CommandHost` describes the shell it is handed (`CommandAgent`, `CommandTranscript`) as abstract base classes the terminal's classes inherit, so it names nothing of the terminal. |
   | `entries`, `presenters` | The row model and `Presenter`/`Presenters`: a plugin subclasses the one and registers into the other. `CONTENT_INDENT`, `Indented` and `LeadingGap` go with them because `Presenter.block` is written in terms of them. |
   | `pets` | `Pet` and `PetSource` are what a pet plugin builds, and `pixel_lines` is the format they are written in; the bundled pets stay in the app. |
   | `host`, `panels`, `switch` | `HostLink`, `bottom_panel`/`pressed` and `draw_switch` are what a plugin's panel imports. They depend on the widget framework only, so the plugin does not need the application to draw one. |

   What stayed in `zettcode-presenters` is the concrete presenters, `BUILTIN_PRESENTERS`/`DEFAULT_PRESENTERS`,
   `render_entry`/`block_for`, the wording they use (`text`, which now also owns `compact_tokens`), the pulse and the
   brand mark. `zettcode-app` keeps the transcript, the projector, the replay and `BuiltinPresenters`, the ten-line
   plugin that registers them.

   **The runtime names left the facade.** `TuiGroups`, `UiSlots`, `TerminalLoader`, `load_terminal_plugins` and
   `terminal_context` are what a *running program* has; a plugin author does not construct them, so they are no longer
   re-exported from `zettcode.plugin_api` (nothing in the guide or in either plugin used them). The facade resolves each
   name on first use, because the boot frame imports a row constant before the settings or a provider SDK exist.

   **A part of the program cannot be switched off.** `[plugins] disable`, the switch file and the `/plugins` panel
   reach only what an entry point makes discoverable. A part of the program is listed by the program (`builtins=`), loads
   before any distribution is looked at, and has no entry point, so none of them reaches it; one that is an optional
   feature declares a `PluginSetting` and is switched by that key. A hand-written `disable` line that names a part is
   ignored and logged (`plugins.required`). `test_required_plugins.py` holds it against the real list of built-ins, and
   `test_a_part_the_program_is_made_of_is_never_discoverable_as_a_plugin` holds the other side: a distribution that is
   a part must not declare the entry point. The next part to be split out (themes, pets, the shell's rows) follows the
   same cut: contract in `plugin-api`, implementation in its own package, listed by the app, never an entry point.

## What changes for a reader and a plugin author

```python
# before
from zettcode import ZettCodeConfig, ZettCodeEngine   # and: import zettcode; zettcode.__version__
from zettcode.app.plugins import TuiPlugin, PluginContext

# after
from zettcode.config import ZettCodeConfig          # what the engine's settings are, shipped by `zettcode-engine`
from zettcode.engine import ZettCodeEngine
from zettcode.version import __version__
from zettcode.plugin_api import TuiPlugin, PluginContext
```

`pip install zettcode` still writes both console scripts, and `pip install "zettcode[monitor]"` still adds `/monitor`.
An agent plugin installs `zettcode-plugin-api` and nothing else.
