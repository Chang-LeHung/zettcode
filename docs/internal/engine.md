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

`zettcode.ZettCodeRuntime` and `zettcode.app.ZettCodeRuntime` were published, so they stay as aliases that warn
(`DeprecationWarning`) for at least one minor version.

## Steps (one pull request each, `make check` green)

1. **Name.** `ZettCodeRuntime` → `ZettCodeEngine`; `zettcode.engine` facade; deprecated aliases; invariants for
   the layering below.
2. **Types.** Move events, values and `_translate` under the engine; the SDK re-exports.
3. **Terminal.** The TUI projector consumes engine events instead of raw `zett_agent` events.
4. **Seal.** `sdk` imports nothing from `app.*`; `test_structure` pins it.

## Layering rules to pin

- `sdk` and `server` do not import `app.ui`.
- `engine` does not import `app.ui`, `sdk` or `server`.
- `tui` still imports neither `zett_agent` nor the application.
