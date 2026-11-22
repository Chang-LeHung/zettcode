# Plugin child inheritance

A tool backend must not silently become another backend when a session delegates or starts a daemon.
Inheritance is explicit and keyed by **`Plugin.name`**, not entry-point origin or command-line flags.
Plugins import the shared contract from `zettcode.plugin_api`:

```python
from typing import Any
from zettcode.plugin_api import CHILD_STATE, ChildSession, Plugin, PluginContext

class Backend(Plugin[PluginContext]):
    name = "backend"

    def export_child(self, child: ChildSession) -> dict[str, Any] | None:
        return {"target": self.target}  # JSON only, no live connection

    def restore_child(self, state: dict[str, Any]) -> None:
        self.target = state["target"]  # BEFORE activate

    def child_extensions(self, child: ChildSession) -> tuple:
        if child.profile == "reasoning":
            return ()
        return (self.make_extension(profile=child.profile),)  # fresh per call
```

`ChildSession` is a frozen dataclass with `kind: Literal["subagent", "daemon"]` and
`profile: str | None = None`. The service key `CHILD_STATE` is `"plugin_child_state"`.
All three hooks default to no work (`None`, no-op, `()` respectively).

## In-process subagents

`AgentBuild.plugins` carries the loaded collection to the SDK's Subagents factory. At **each child creation**,
the factory calls every active plugin's `child_extensions(ChildSession("subagent", profile))`, including
`explore` and `reasoning`, not just the inheriting `coding` profile. It does not call export/restore or create a
plugin host for the child. The plugin owns its profile boundary: a read-only backend must keep exploration
read-only and reasoning may return nothing. SSH deliberately refuses unknown profiles: their tool boundary has
not been audited, and allowing their default tools could silently restore a local backend.

Fresh extensions replace definition defaults and inherited parent extensions **by extension name**. Duplicate
names from child hooks fail rather than picking a winner. Existing third-party extensions with no hook remain
subject to the existing coding sharing predicate; plugin hosts themselves are never shared. Thus a plugin that
needs independent per-child state must implement the hook rather than rely on shared host state. The plugin
owns resources its factory creates; the hook must not hand back a mutable singleton intended for one session.

## Daemons

`Client.spawn_daemon(...)` exports from the active client at call time; workspace defaults to the client's.
Model and effort retain the module helper's defaults. **Permission defaults to the client's current policy**,
including changes made with `use_permission`; `ask` maps to `deny` because there is nobody to approve shell
commands. A trusted caller can explicitly choose another level (including `full`), but inheritance never
escalates automatically. The module-level `sdk.spawn_daemon` has no active client and therefore no implicit
plugin snapshot or policy; its existing `full` default remains, and it accepts `plugin_state=` for explicit callers.

The SDK registers `PluginChildEnvironment` outside the plugin host's tool middleware. Around a model-issued
`bash`, it exports a daemon snapshot and overlays `ZETTCODE_PLUGIN_CHILD_STATE` for that task's subprocesses.
This makes `python -m zettcode daemon spawn` inherit the active state too, even when a plugin replaces the local
bash handler. There is no mutation of process `os.environ`; parallel tools and cancellation cannot leak the
handoff. Tools expose `shell_environment` and `subprocess_environment` (re-exported by plugin-api) for a backend
that starts its own local subprocess. A backend must pass `subprocess_environment()` as that subprocess's `env`;
this is not an instruction to export the handoff into a remote login environment. The safe shell wrapper passes
only the validated task-local child-state key as the sandbox's extra environment. `env -i` still strips host
credentials, other task overlays and stale process handoffs; tools do not import engine validation.

The `spawn` and `run` commands consume/remove their environment copy before building the child. JSON is checked
without coercion: an object of nonempty plugin names to objects; string object keys; finite numbers, strings,
booleans, null and lists only. Malformed JSON, duplicate keys, non-finite numbers and unsupported values fail.
An empty object for a named plugin still requires that plugin. Loader restoration happens before activation,
and missing, disabled or failed inherited plugins make the entire start fail closed. An inherited default-off
plugin is selected when available; explicit disable still refuses rather than overriding the reader's choice.

`Options.plugin_state` and durable `State.plugin_state` are separate from `plugin_arguments` (entry-point
command-line values). Permission restarts, their rollback, broker companions and an explicit daemon resume
forward the saved state. A resume with a remembered nonempty state refuses a conflicting nonempty snapshot;
no snapshot or an empty snapshot preserves the remembered backend. Old records with no field retain the old
behavior. Before readiness and on every later mark, the daemon exports **actual activated plugins**, not merely
the incoming `Options.plugin_state`. Export errors stop the daemon and remove its heartbeat without replacing
the last good descriptor — with one exemption: the final `stopping` mark does not export at all, because a
stopping daemon is not inheritable any more and a failing export there would raise out of `serve`'s `finally` and
strand a record a `kill` asked to remove. That write carries the last successful export instead. A failed resume
restores the previous durable record (including arguments and
backend), even when the child died after writing `starting` or removed its failed record. Launch `OSError`s
are reported as `SpawnFailed` / SDK `DaemonStartError`.

Serialized JSON is limited to **16 KiB**, including the combined child state and plugin-argument handoff on
spawn. Oversized descriptors fail with a size-limit error before a process is launched. Durable loading also
rejects duplicate keys and malformed fields; an unreadable descriptor is listed by folder name, but a resume or
read-modify-write refuses rather than silently discarding it. Old records with missing optional fields remain
readable. Omitted `plugin_arguments` centrally preserve the saved arguments. CLI resumes apply only explicitly
typed plugin overrides (even explicit boolean defaults); a fresh CLI spawn uses declared defaults.

This state belongs to the daemon record, not the conversation store: resuming an ordinary session, or a daemon
whose record was deleted, cannot recover an inherited backend that was never otherwise configured.

Export state is kept in the daemon's record and carried in the child environment, not printed or placed
on argv. It is **not** an encrypted secret store: plugins should export non-secret connection descriptors and
resolve authentication through their own secure configuration. A backend can refuse export or restore when it
cannot preserve its invariants; such refusal is preferable to a child running locally by accident.
