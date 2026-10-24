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

The terminal should end up a client of the SDK like the server is (step 4 below). Today it still drives
`TerminalAgent` (the engine's agent plus the shell's own parts) directly.

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

1. **SDK gaps.** The terminal calls 76 distinct members of its agent; 59 have no SDK counterpart. Many are only
   named differently (`active_model` / `Client.model`, `list_sessions` / `Client.sessions.list`). The real gaps are
   the raw `stream`, `resume_point`, `resume_blocker`, `stream_resume` and the approval and question replies; the
   session locks (`session_locked`, `retake_session`, `require_session`); and reading and writing the model entries
   of the config file. Each is decided one by one — general (into the SDK) or the terminal's own (stays in `app/`) —
   because whatever enters the SDK is a promise.
2. **Terminal on the SDK.** The terminal drives `sdk.Client`; `TranscriptProjector` consumes SDK events, so events
   are translated once (`sdk/_translate.py`). `pets`, `themes`, `presenters`, `plugin_rows`, `plugin_commands` and
   the `Transcript` stay the terminal's. The two things to keep: the first frame before the provider exists
   (`preview` / `start`), and the session load on a worker thread.
3. **Seal.** `app` reaches the engine only through the SDK; a layer rule in `test_structure` says so.
