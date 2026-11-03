# Splitting `zettcode` into namespace packages

Status: **stage 1 landed**, stages 2–5 are the plan. This is the contract for the migration: the target shape, who
owns every module, and the order the work lands in. Each stage ends green — `make check` plus the plugin suites — and
is committed on its own, so a stage that goes wrong can be reverted without taking the rest with it.

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
| `zettcode-engine` | `zettcode/engine/**`, and the leaves the runtime needs: `config`, `config_edit`, `paths`, `providers`, `prompt`, `relay` (the marker), `wording`, `filelock`, `error_text`, `budget`, `modes`, `logging_setup`, `processes`, `_compat`, `plugin_tui`, `mentions` (the protocol) | `zett-agent`, `pydantic` |
| `zettcode-tui` | `zettcode/tui/**` and a local `tui/_compat.py` | — (no distribution of ours) |
| `zettcode-broker` | `zettcode/broker/**` | `zettcode-engine` (filelock, logging_setup, modes, processes) |
| `zettcode-sdk` | `zettcode/sdk/**`, `zettcode/daemon/**`, `zettcode/doctor.py`, `zettcode/mentions.py` (the implementation), `zettcode/relay.py` (the wire half), `zettcode/registry.py`, `zettcode/table.py`, and the composition root `zettcode/sdk/builtins.py` | `zettcode-engine`, `zettcode-broker` |
| `zettcode-server` | `zettcode/server/**` | `zettcode-engine`, `zettcode-sdk` |
| `zettcode-gateway` | `zettcode/gateway/**` | `zettcode-engine`, `zettcode-sdk` |
| `zettcode-app` | `zettcode/app/**`, `zettcode/collector.py`, `zettcode/statusline.py` (the rendering half) | `zettcode-engine`, `zettcode-tui`, `zettcode-sdk`, `zettcode-broker` |
| `zettcode-plugin-api` | `zettcode/plugin_api/**`: re-exports only, the surface a plugin imports | `zettcode-engine`, `zettcode-tui`, `zettcode-app` |
| `zettcode` | `zettcode/cli.py`, `plugin_cli.py`, `oneshot.py`, `update.py`, the console scripts, the built gateway page | all of the above |

`zettcode` stays the distribution a reader installs: it keeps both console scripts (the rules for that are in
`AGENTS.md`) and depends on the server, so one `pip install zettcode` is unchanged in effect.

`zettcode-broker` needs four leaf modules that live in the engine package. That edge is accepted: the alternative is a
`zettcode-base` package between them, which would put a second dependency back in front of a plugin.

## Who owns the loose modules

| Module | Owner | Why |
| --- | --- | --- |
| `_compat` | engine | `StrEnum`/`tomllib`; the engine's storage and permission use it. `tui` gets a copy of the 12 lines it needs, so the framework stays dependency-free. |
| `budget`, `error_text`, `filelock`, `logging_setup`, `modes`, `paths`, `processes`, `prompt`, `providers`, `wording`, `config`, `config_edit` | engine | Leaves with no dependency of ours; the runtime or its settings need them, and everything above imports them from here rather than re-owning them. |
| `plugin_tui` | engine | The `TuiGroup` ABC the engine's plugin context names; the terminal implements it. It is also the first thing `zettcode-plugin-api` re-exports. |
| `mentions` | split: protocol in engine, `FileMentions`/`SkillMentions` in sdk | The engine only needs the type; the implementation reads the workspace, the broker and the registry. |
| `relay` | split: `Relayed` in engine, the broker-facing half in sdk | `agent/turns.py` marks a relayed message; building and reading one needs the broker. |
| `statusline` | split: `NAMES`/`TURN_PREFIX` in engine, the rendering in app | `config.py` validates the `[statusline]` table and must not import the statusline's sdk and tui edges. |
| `collector` | app | The terminal's collector policy. |
| `doctor` | sdk | It runs model checks through the SDK. |
| `registry` | sdk | Shared by the mentions implementation and the app. |
| `table` | sdk | The daemon's output and the program's. |
| `update` | program | It reads the program's own version and release check. |
| `cli`, `plugin_cli`, `oneshot` | program | The console scripts. |

## What leaves the engine

The engine keeps the runtime: dialogue, storage, permission, tools, the extension machinery, the plugin machinery and
their data types. What is *composition* or *config-file writing* moves up, because it needs a broker, a config file or
a third-party library the engine must not carry:

| Today | Moves to | Because |
| --- | --- | --- |
| `engine/plugins/builtin_agent.py` (`AGENT_PLUGINS`) | `zettcode/sdk/builtins.py` | It composes the tools, storage, usage, permission, compaction, MCP, messaging and mention plugins. The server needs it too, so the SDK — not the app — is its home. |
| `engine/messenger.py` | `zettcode/sdk/messenger.py` | It speaks to the broker (httpx/websockets). `ZettCodeEngine.preview` stops creating one; the caller passes it (`messenger=None` by default). |
| `engine/extensions/messaging.py` | `zettcode/sdk/extensions/messaging.py` | Broker client and modes. |
| `engine/extensions/context.py` | `zettcode/sdk/extensions/context.py` | `tiktoken`, which the engine must not carry. |
| `engine/extensions/mcp.py` | `zettcode/sdk/extensions/mcp.py` | The MCP client and its config. |
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
2. **Split the shared modules.** `mentions`, `relay` and `statusline` become a type half in the engine and a logic
   half above it; `extensions/context` loses its `tiktoken` half the same way. After this stage no engine file
   imports anything outside `zettcode.engine` except the leaves the engine ships.
3. **The namespace and the wheels.** Delete `zettcode/__init__.py`; give every distribution a `packages/zettcode-*/`
   directory, a `pyproject.toml` and a `__version__`; add them to the uv workspace, `[tool.uv.sources]`, Ruff, mypy, the
   Makefile and CI. Every test that used the facade or `zettcode.__version__` is updated.
4. **`zettcode-plugin-api`.** Add the thin re-export package and move the two plugins onto it (`monitor`'s imports
   become `from zettcode.plugin_api import TuiPlugin, CommandContext, ...`). This is the stage that pays for the split.
5. **Releases, packaging and docs.** Per-package tags through `release-packages.yml`, `make smoke` for the program's
   wheel and the engine's, `AGENTS.md` / `RELEASING.md` / the guide, the invariant rows for the new rules (engine
   imports nothing of ours; a plugin depends on `zettcode-plugin-api` and nothing else).

## What changes for a reader and a plugin author

```python
# before
from zettcode import ZettCodeConfig, ZettCodeEngine   # and: import zettcode; zettcode.__version__
from zettcode.app.plugins import TuiPlugin, PluginContext

# after
from zettcode.engine import ZettCodeConfig, ZettCodeEngine
from zettcode.plugin_api import TuiPlugin, PluginContext
```

`pip install zettcode` still writes both console scripts, and `pip install "zettcode[monitor]"` still adds `/monitor`.
An agent plugin installs `zettcode-plugin-api` and nothing else.
