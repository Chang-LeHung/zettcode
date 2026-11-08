# Plugin dependencies and a small core

Direction: the application keeps only what loads plugins and runs the conversation loop. Everything else — rows,
presenters, pets, themes, commands, usage, the agent's own tools — is a plugin found through an entry point.

## Done

- `Plugin.deps: tuple[str, ...]` names the plugins a plugin needs. `engine/plugins/graph.py::order` returns a stable
  topological order (no edges ⇒ the order offered) and the reason each other plugin cannot load: a need that is
  missing or turned off, a need that failed, a cycle (named), a plugin listing itself.
- `run(..., required=(...))`: names the program cannot run without. A `disable` line that names one — or anything a
  required plugin needs — is ignored and logged as `plugins.required`; a required plugin that still did not load
  raises `RequiredPluginError(missing={name: why})`, which is how "no presenters ⇒ it does not start" is expressed.
- Names are unique. Dependencies are resolved by name, so the name is the identity. An entry point or file that takes
  the name of another plugin loses it and is logged (`plugins.name_taken`).
- Services: `ctx.inject(name, obj)` (same as `provide`) publishes, `ctx.service(name, kind)` / `ctx.find(...)` reads.
- One entry-point group, `zettcode.plugin`: one line per plugin class, whichever part of the program it is. The role
  of a point is decided by the **distribution** it came from (`PROGRAM_DISTRIBUTIONS` in the engine's loader), which
  `importlib.metadata` knows before the plugin's module is imported:
  - `agent`: the parts that compose the agent. 10 are published by `zettcode-sdk`; `zettcode-skills`
    (`skills`, `skill-tool`), `zettcode-messaging` (`messaging`), `zettcode-mcp` (`mcp`), `zettcode-files` (`files`),
    `zettcode-jit-harness` (`harness`), `zettcode-ask-user` (`ask-user`), `zettcode-instructions`
    (`project-instructions`), `zettcode-todos` (`todos`), `zettcode-tool-output` (`tool-output`),
    `zettcode-truncation` (`long-output`) and `zettcode-guidance` (`tool-guidelines`) are distributions of their own.
    Every loader reads them (the engine's own default does not: `agent=False`). None can be switched off — they are
    protected like a compiled-in plugin, `[skills] enabled` and the other configuration keys being what turns a feature
    off — but a failure to activate one is recorded in `failed`, not raised, as it was when they were compiled in.
  - `terminal`: parts only a screen has a use for (`presenters`, `pets`, `themes`, `commands`). The SDK and the server
    do not load them, so the terminal's packages are never imported there. `REQUIRED_PLUGINS = (shell, presenters,
    commands)` in `app/plugins/loader.py`.
  - anything else: what a reader installs, published on its own line with its own version (`[tool.zettcode] plugin =
    true` in its `pyproject.toml` is what the release order looks for). The two old group names (`zettcode.plugins`,
    the parts' `zettcode.agent`/`zettcode.terminal`) are still read, so a wheel published before the merge keeps
    loading.
- Order inside a group is `(Plugin.rank, name)`, then `deps`. `AGENT_PLUGINS` in `sdk/builtins.py` is the one list that
  says the order of the SDK's own (and gives each class its rank); the entry points in the SDK's `pyproject.toml`
  repeat it, and `test_agent_parts.py` and `test_structure.py` hold the two, and the suite's literal copies in
  `support/conftest.py`, together. The only service one reads from another is `subagents` ← `capabilities`, written
  as a `deps`. A part in another distribution states no rank: its extension has a `priority` of its own (the
  skills 80, MCP 70, project instructions 10, against the 100 nearly everything else shares), and the agent sorts by
  that. Registration order still decides, though, wherever a priority is shared: a part with no rank is activated at
  rank 0, sorted by name among themselves and beside the SDK's `coding`, which has rank 0 too — `ask-user`, `coding`,
  `files`, `harness`, `long-output`, `mcp`, `project-instructions`, `skill-tool`, `skills`, `todos`,
  `tool-guidelines`, `tool-output` — and what the SDK lists from `capabilities` on follows by rank. Within the 100
  band that registration order is the run order, which is the list
  `test_the_order_the_agent_runs_them_in_is_the_priority_of_each` pins: `ask-user`, `coding`, `long-output`, `todos`,
  `tool-guidelines`, `tool-output`, `subagents`, the shell's approval, the store, the usage and context counters, then
  the compaction; the extensions at 10, 50, 80, 110 and 120, and the harness far above them, stand where their own
  priority puts them around those.
  That order is visible in one place and only there: the tools array a provider is handed is
  `tuple(tool.definition for tool in context.tools.values())`, so `ask_user` is now offered before `read` and
  `todo_write` before `task`, where before the move they were last and second to last. Nothing else reads a
  position — the shell reads the plan by name, the model picks tools by name — so the tools array is the whole
  effect, and `test_plugin_extensions.py` pins it. What registration order used to decide for the skills — a skill
  beating a file of the same name in `@` — is `MentionProvider.precedence` now (a session −20, a skill −10, anything
  else 0).
- `require_agent_parts(plugins)` refuses an installation that lacks any of the parts (`REQUIRED_AGENT_NAMES`: the
  SDK's own plus `files`, `harness`, `skills`, `skill-tool`, `mcp`, `ask-user`, `project-instructions`, `todos`,
  `tool-output`, `long-output`, `tool-guidelines`), in the
  SDK's and the terminal's loaders: a damaged one would otherwise start an agent with no file references, no skills, no
  MCP or no way to ask the reader a question, silently.

## Triggers

`ctx.agent.register_trigger(trigger, handler)` (engine `plugins/triggers.py`). A `Trigger` is a coroutine that calls
`fire(payload)`; its `scope` is `PROCESS` (one per process, enforced by a module-level owner table) or `MACHINE` (one per
machine, a `SingletonLock` on `<store parent>/triggers/<name>.lock`; the losers poll every `RETRY_SECONDS` and take over
when the holder exits or dies). `ZettCodeEngine.start()` starts a `TriggerHost` for `Plugins.triggers` and `aclose()`
stops it before anything else, so the machine lock is let go first. Triggers start before the model check, so a machine with no model still runs them. Not done: a trigger
that fails is not restarted, and its status is read through `ZettCodeEngine.trigger_statuses()`, `Client.plugins.triggers`, and the server's `/plugins` answer (no `/plugins` row in the terminal yet). Invariant P12.

## Delivering into the agent

An event that is not the reader's — another session's message, a trigger, a webhook — has the same two ways in as one
typed during a request. The engine owns the machinery (`zettcode.engine.delivery.Delivery`, provided as `DELIVERY`:
`busy` counts the requests a runtime has open, `steer` hands a message to the one running, `when_idle` calls back after
the last one ends, at once when nothing runs). `zettcode-engine` also publishes the queue's *contract* — the `INBOX`
name, `Waiting`, and the abstract `Inbox` in `zettcode.engine.inbox`, re-exported by `zettcode-plugin-api` so a plugin
types the service without importing the queue's package — while `zettcode-messaging` owns the queue itself
(`Inbox`, provided as `INBOX`): `deliver(message, mode=..., payload=...)` steers while a request runs and queues
otherwise, draining one turn at a time when the runtime is idle and a front end has registered a starter
(`start_with`), which is the front end's own way of starting a prompt. A front end that supplies an `Inbox` under
`INBOX` through `preview(shared=...)` keeps it; the plugin builds one only when none is there. Two messages from
another session that waited next to each other start as one turn (`batch_size`/`merge`); a plain event is always a
turn of its own. The queue has a
cap; the overflow is refused as `FULL`, which the broker turns into "busy, try again".

`Relay` (same package) is what a message from another session adds on top of the queue: the `Receipt` its sender's agent
reads, the record of what the running request was handed (`steered`/`adopted`) and the return of a steer the run never
read (`settle`), and the drawing hook a front end uses while one waits. A front end supplies `busy`, `steer`, `start`
and its inbox; the terminal's `ui` package now holds none of the queue, the cap or the receipts.

`Client.deliver` is the SDK's way in, and it also registers the SDK's starter, so a program's follow-ups run through
`prompt` exactly as its own turns do; a message another session sent runs through `Session.relay`. The terminal
registers its starter from `_start_messaging` and asks the inbox again after every turn (`_start_next_command`), because
the runtime's idle notice lands before the shell clears its own busy flag.

## Left

- Nothing to move: `usage_charts` intentionally stays in `app` because the sessions and context pages share its
  drawing primitives with `/usage`.
