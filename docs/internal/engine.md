# The engine

One agent core, several faces. `ZettCodeEngine` (`engine/core.py`) and the agent built on it
(`zettcode.engine.agent.ZettCodeAgent`) do the work. The SDK is the one public face of it; the terminal and, through
the SDK, the HTTP server are its users. "Harness" stays what it already meant here — the just-in-time harness mode the
model can be put in (`HarnessSwitch`, `/harness`, `Client.use_harness`) — and is not the name of the core.

## Layers

```
engine   the agent core; internal, free to change; imports no app, no sdk, no server
  ▲
sdk      the public face: Client, Session, events, value types, errors; imports the engine only
  ▲        ▲
terminal   server ── TypeScript client ── VS Code
```

The terminal is not yet a client of the SDK the way the server is, but it reads the agent's events through the SDK's
translation (`sdk/translation.py`): `TranscriptProjector` is the agent client's dispatcher and draws the SDK's typed
events, so events are translated once. It stays a dispatcher, not a `RunStream` consumer, because some events happen
outside any run (a compaction the reader asked for, an MCP server starting) and the dispatcher is what sees them.
In exchange the five events that open and close a span (`ReasoningStarted`, `ReasoningFinished`, `CompactionDelta`,
`SteeringFinished`, `SteeringInterrupted`) became part of the SDK.

## Compatibility contract

Frozen, because the server, the TypeScript client and the extension are built on it:

1. every name in `zettcode.sdk.__all__`, with its signature;
2. every event and value-type field in `sdk.events` / `sdk.types` (fields are added, never renamed or retyped);
3. the server's wire format, which follows from 1 and 2.

The engine is not part of the contract. There are no third-party plugins either, so nothing here keeps an old name:
`ZettCodeRuntime` and `zettcode.plugins` were renamed outright.

## Where things are

In `zettcode/engine/`: `core.py` (`ZettCodeEngine`), `agent/` (`ZettCodeAgent`, built from the mixins `base`,
`settings`, `context`, `sessions`, `turns`, `interaction`, `exports`, plus `prompt`), `dialogue/`, `extensions/`,
`permission/`, `storage/`, `tools/`, `export/`, `plugins/`, `pipeline.py`,
`server_tools.py`, and the messaging between sessions (`messenger.py`).

Shared by the engine, the SDK and the views, and so at the top and not under the engine: `budget.py` (the names of the
context's sources), `wording.py` (the word for an unnamed session), `error_text.py` (`describe_error`), `registry.py`
(the ordered registry the commands and the `@` resources are both built on), `mentions.py` (the `@` resources),
`prompt.py` (the parts of a user turn) and `relay.py` (a message from another session, and how it is stored).

Reading a stored session builds no terminal rows: the engine's `load_session` returns `StoredSession`, and the
terminal replays it into its own `Transcript`.

The terminal's part is `TerminalAgent` (`app/agent/agent/`): the engine's agent plus `commands.py` (slash commands,
themes, pets, `Presenters`, what plugins contributed) and `settings.py` (`AppearanceMixin`: theme, pet, status line).
The status-line formatters live in `statusline.py`, because they are about the terminal.

**Plugins.** `zettcode.engine.plugins` is what the agent uses: `Plugin` (generic over its container), `AgentPlugin`,
`PluginContainer` (extensions, services, `@` providers, model providers), the loader and `Plugins`, and the plugins
the engine ships. `zettcode.app.plugins` adds what only a terminal has: `TerminalPlugin`, `TerminalContainer`
(commands, palettes, pets, presenters, the header and status rows), `TerminalLoader`, `TerminalPlugins`, and the
shell's own plugins. The engine is handed its loader (`ZettCodeEngine.preview(config, load)`) and `TerminalAgent`
hands it the terminal's, so the SDK and the server load the engine's plugins and none of the terminal's.

Pinned by `test_structure.py`: the layer table (`engine` imports no `app`, `tui`, `cli`, `sdk` or `server`; `sdk`
imports no `app`, `tui`, `cli` or `server`) and `test_importing_the_engine_loads_nothing_of_the_application`, which
reads what a fresh interpreter loads, so a dependency that goes round through the plugins shows up.

## What is left

Each its own pull request, `make check` green.

1. **Done: one translation.** The terminal's projector draws SDK events.
2. **Done: the views import no engine.** See the next section for what that does and does not cover.
3. **Done: the runs.** A turn, a side question and a continue go through the SDK, with answers deferred to the panels.
4. **Done: the session and the simple settings.** Two new SDK pieces made it possible: `sessions.read`/`install` and
   `Session.retake`, and `use_permission(remember=)`. The rest is the list above.

## What the seal means

The terminal's views (`app/ui`, `app/commands.py`) import nothing from `zettcode.engine`, and `test_structure.py` says so
twice: in the layer table, and in `test_the_views_of_the_terminal_import_nothing_of_the_engine`, which also catches an
import made inside a function. What they hold instead is an SDK client (`TerminalAgent.client`, built with the SDK's
private `Client._around`) and the terminal's agent. Data the views draw comes from the SDK (`WorkspaceUsage`,
`ContextReport`, `SessionInfo`, `SessionStatsInfo`, `Usage`) or from the shared leaves above, and the engine objects they
hold (`SessionLink`, `StoredSession`) are named by `app/agent`, which is where the terminal is put together from the
engine's parts and so may import it (as may `app/plugins`).

It is a wall around imports, and only partly around calls. The three ways the shell starts a run now go through the SDK:
a turn (`client.session.prompt`, or `relay` for a message another session sent), a `/btw` question
(`session.ask_stream`) and `/continue` (`session.resume_stream`). They are started with `defer_answers=True`, so an
approval or a question opens its panel from the handler and the reader answers from the panel with the event's own
`approve`, `deny`, `answer` or `decline` (invariant H22); the SDK resolves a draft's `@` references with the registry
the composer completed them from (the plugins' providers, and the other sessions first), and the shell words a failure
from the SDK's `RunError` (`app/ui/turns.py`). The projector no longer carries the panels' handlers: it draws the
transcript, and the run asks.

The views now read the session (id, title, lock, path, workspace), name, fork, retake and load it (`sessions.read_blocking`
then `sessions.install`), read and set effort, permission, harness and self-compaction, list, pick and edit the models
(`client.models`, `use_model`, `model_entries`, `add_model`, `update_model`, `remove_model`; the pickers and forms hold
the SDK's `ModelInfo`), read the plan, and steer with pictures and `@` references (`Session.steer` returns the text the
run reports the message by), all through the SDK's client. `test_the_shell_does_not_reach_round_the_sdk_for_what_the_sdk_offers`
keeps each of those names off the terminal's agent.

What the views still take from `TerminalAgent`:

- `pets`, `themes`, `statusline_*`, `presenters`, `plugin_*`, `commands`, `conversation`: the terminal's own parts.
- `runtime`: the configuration values the terminal reads directly (`runtime.config.*`), and the two-stage start
  (`runtime.start()`, so the first frame paints before the engine is ready), which the SDK has no public form of.
- `require_session`, `resume_blocker`: the reason a session cannot be written or continued, worded for the reader.
