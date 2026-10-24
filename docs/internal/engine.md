# The engine

One agent core, three faces. The terminal (`app/ui`), the SDK (`zettcode.sdk`) and, through the SDK, the HTTP server
all drive the same object, and that object is the **engine**: `ZettCodeEngine`, today `ZettCodeRuntime`.

"Harness" stays what it already means here — the just-in-time harness mode the model can be put in
(`HarnessSwitch`, `/harness`, `Client.use_harness`). It is not the name of the core.

## Today

```
app/ui (TUI) ──► ZettCodeAgent ──► ZettCodeRuntime ◄── sdk.Client ◄── server ◄── TS client, VS Code
       │                                                     │
 TranscriptProjector                                   sdk/_translate.py
 (zett_agent events → Transcript)                      (zett_agent events → sdk events)
```

Two translations of the same events, and the SDK reaches into `app.agent.*` in some forty places for internal types.

## Target

```
sdk            public, stable: Client, Session, events, value types, errors.   imports engine only
engine         ZettCodeEngine + the events and values it emits.                imports no ui, no sdk, no server
app/ui         TUI; projects engine events into its Transcript.                imports engine
server         unchanged rule: drives zettcode.sdk and nothing else
```

- `zettcode.engine` is importable and supported for programs that want the core without the SDK's conveniences, but
  the guide documents the SDK. The engine's own surface is small on purpose.
- The event and value types move to the engine (`engine.events`, `engine.types`) and `zettcode.sdk.events` /
  `zettcode.sdk.types` re-export them, so the names and fields users already have do not change.
- `_translate.py` becomes the engine's one translation. The TUI projector consumes the same events.

## Compatibility contract

Frozen, because the server, the TypeScript client and the extension are built on it:

1. every name in `zettcode.sdk.__all__`, with its signature;
2. every event and value-type field in `sdk.events` / `sdk.types` (fields are added, never renamed or retyped);
3. the server's wire format, which follows from 1 and 2.

`ZettCodeRuntime` is renamed outright, with no alias.

## Where things are now

Moved into `zettcode/engine/` so far: `core.py` (`ZettCodeEngine`), `dialogue/`, `extensions/` (including
`messaging.py`), `permission/`, `storage/`, `tools/`, `export/`, `errors.py`, `pipeline.py`, `registry.py`, and the
messenger (`messenger.py`, `relay.py`). The status-line formatters that used to sit in `extensions/usage.py` moved
to `statusline.py`, because they are about the terminal.

Still to move: the `ZettCodeAgent` mixins in `app/agent/agent/`. They mix three things that must be pulled apart:
the engine's own work (`turns`, `sessions`, `settings`, `context`, `exports`, `interaction`), the terminal's slash
commands (`commands.py`: themes, pets, `Presenters`), and the terminal's `Transcript` view model, which the mixins
fill directly. The engine half goes to `engine/`; the TUI projects engine events into its own `Transcript`.

Open: `engine/core.py` imports `zettcode.plugins`, and the built-in plugins import the terminal's views. The direct
rule (`test_layers_only_import_downwards`) holds, the indirect one does not yet.

## Splitting `ZettCodeAgent` (proposal, not started)

The mixins in `app/agent/agent/` are mostly the engine already; three seams tie them to the terminal.

| Part | Goes | Why |
| --- | --- | --- |
| `base`, `turns`, `interaction`, `context`, `settings` (models, effort, permission, harness, self-compaction), `exports`, `prompt` | `engine/agent/` | no terminal types in them |
| `settings.remember_theme`, `remember_pet`, `remember_pet_position`, `remember_statusline`, `reduced_motion` | terminal (`app/agent`) | they persist terminal preferences |
| `commands.py` (`/new`, `/export`, themes, pets, `Presenters`, status-line commands) | terminal | slash commands and views |
| `sessions.load_session` / `install_session` | split | see below |

**Sessions.** Today `load_session(session_id, transcript)` replays a stored session into the terminal's `Transcript`
and `install_session` also fills it; the SDK builds an empty `Transcript` only to call them. After the split:

- `engine.load_session(session_id)` reads the store and returns `StoredSession(session, title, model, usage)`; the
  usage totals come from the stored lines, without decoding a message (what `replay` already does for old lines).
- `engine.install_session(stored)` does the engine half: active session, usage seed, model, context report.
- The terminal calls `replay(stored.session, …)` itself, on the same worker thread, and fills its `Transcript`.
- The SDK no longer builds a `Transcript` at all, and `sdk` stops importing `app.agent.conversation`.

**Plugins.** `engine/core.py` imports `zettcode.plugins`, and the built-in plugins import terminal views (usage page,
sessions page, presenters). The engine cannot be free of `app` until `plugins/` is cut in two: the host, services
and the agent-side plugins (`builtin_agent`: extensions) belong to the engine; the commands, status-line parts and
UI rows (`builtin_commands`, `builtins`) stay with the terminal. A plugin that provides both is registered by the
terminal on top of the engine's. This changes where third-party plugins import from, so it needs your decision
before it starts.

**Events.** `TranscriptProjector` and the SDK's `_translate` both read `zett_agent` events. After the split the
engine emits one event vocabulary (today's `sdk.events`, moved to `engine/events.py`), `_translate` becomes the
engine's, and the projector consumes those events.

Order, each its own pull request: (a) sessions and the SDK's `Transcript`; (b) move the agent mixins and send the
terminal's parts back; (c) events; (d) plugins; (e) the indirect-import rule in `test_structure`.

## Steps (one pull request each, `make check` green)

1. **Name.** `ZettCodeRuntime` → `ZettCodeEngine`; `zettcode.engine` facade; invariants for the layering below.
2. **Types.** Move events, values, `_translate` and the messenger (session-to-session messaging belongs to the
   core) under the engine; the SDK re-exports.
3. **Terminal.** The TUI projector consumes engine events instead of raw `zett_agent` events.
4. **Seal.** `sdk` imports nothing from `app.*`; `test_structure` pins it.

## Layering rules to pin

- `sdk` and `server` do not import `app.ui`.
- `engine` does not import `app.ui`, `sdk` or `server`.
- `tui` still imports neither `zett_agent` nor the application.
