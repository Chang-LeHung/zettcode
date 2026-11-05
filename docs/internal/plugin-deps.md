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
- Three entry-point groups, one meaning each:
  - `zettcode.plugins`: what a reader installs. Own version, own release line.
  - `zettcode.terminal`: parts only a screen has a use for (`presenters`, `pets`, `themes`, `commands`). The SDK and
    the server do not load it. `REQUIRED_PLUGINS = (shell, presenters, commands)` in `app/plugins/loader.py`.
  - `zettcode.agent`: the plugins that compose the agent. 17 are published by `zettcode-sdk`; `zettcode-skills`
    (`skills`, `skill-tool`), `zettcode-mcp` (`mcp`), `zettcode-files` (`files`) and `zettcode-harness` (`harness`) are
    distributions of their own, allowed into the group by
    `PROGRAM_DISTRIBUTIONS`. Every loader reads it (the engine's own default does not: `agent=False`). None can be
    switched off — they are protected like a compiled-in plugin, `[skills] enabled` and the other configuration keys
    being what turns a feature off — but a failure to activate one is recorded in `failed`, not raised, as it was when
    they were compiled in. `zettcode-sdk` and `zettcode` depend on both, so installing the program installs them.
- Order inside a group is `(Plugin.rank, name)`, then `deps`. `AGENT_PLUGINS` in `sdk/builtins.py` is the one list that
  says the order of the SDK's own (and gives each class its rank); the entry points in the SDK's `pyproject.toml`
  repeat it, and `test_agent_parts.py` and `test_structure.py` hold the two, and the suite's literal copies in
  `support/conftest.py`, together. The only service one reads from another is `subagents` ← `capabilities`, written
  as a `deps`. A part in another distribution states no rank: its extension has a `priority` of its own (the
  skills 80, MCP 70, against the 100 nearly everything else shares), and the agent sorts by that. What registration
  order used to decide for the skills — a skill beating a file of the same name in `@` — is
  `MentionProvider.precedence` now (a session −20, a skill −10, anything else 0).
- `require_agent_parts(plugins)` refuses an installation that lacks any of the parts (`REQUIRED_AGENT_NAMES`: the
  SDK's own plus `files`, `harness`, `skills`, `skill-tool`, `mcp`), in the SDK's and the terminal's loaders: a damaged
  one would otherwise start an agent with no file references, no skills or no MCP, silently.

## Triggers

`ctx.agent.register_trigger(trigger, handler)` (engine `plugins/triggers.py`). A `Trigger` is a coroutine that calls
`fire(payload)`; its `scope` is `PROCESS` (one per process, enforced by a module-level owner table) or `MACHINE` (one per
machine, a `SingletonLock` on `<store parent>/triggers/<name>.lock`; the losers poll every `RETRY_SECONDS` and take over
when the holder exits or dies). `ZettCodeEngine.start()` starts a `TriggerHost` for `Plugins.triggers` and `aclose()`
stops it before anything else, so the machine lock is let go first. Triggers start before the model check, so a machine with no model still runs them. Not done: a trigger
that fails is not restarted, and its status is read through `ZettCodeEngine.trigger_statuses()` and `Client.plugins.triggers` (SDK only: no server endpoint or `/plugins` row yet). Invariant P12.

## Left

- Shrink `app` further: `shell` and `turn-line` are still compiled in (`BUILTIN_PLUGINS`) and `labels`/`UsagePage` live
  in `app` because the commands open them.
- `AGENT_PLUGINS` is still a list of instances, for callers that load without discovery (most tests). If those move to
  discovery too, it can shrink to the class names.
- A plugin that loses a name is visible only in the log; a `note` on `PluginEntry` would put it on the page.
