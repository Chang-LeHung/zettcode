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
`permission/`, `storage/`, `tools/`, `export/`, `plugins/`, `errors.py`, `pipeline.py`, `registry.py`,
`server_tools.py`, and the messaging between sessions (`messenger.py`, `relay.py`).

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
2. **The rest of the agent's surface.** The terminal still calls 78 members of its agent, and about 40 are engine
   members. Most have an SDK counterpart under another name (`active_model` / `Client.model`, `list_sessions` /
   `Client.sessions.list`, `Session.locked`, `fork`, `compact`, `context`, `resumable`, `steer`, `ask`, `add_model`,
   `use_compact_percent`); the real gaps are small: starting in two stages (`preview`, then `start`), taking a
   session lock back, the model's plan (`tasks`), and writing the self-compaction default to the config file. Each is
   decided one by one, general (into the SDK) or the terminal's own (stays in `app/`), because whatever enters the
   SDK is a promise. `pets`, `themes`, `presenters`, `plugin_rows`, `plugin_commands` and the `Transcript` stay the
   terminal's.
3. **Seal.** `app` reaches the engine only through the SDK; a layer rule in `test_structure` says so.
