# Plugin dependencies and a small core

Direction: the application keeps only what loads plugins and runs the conversation loop. Everything else — rows,
presenters, pets, themes, commands, usage — is a plugin, and nothing is "built in" any more.

## Done (engine)

- `Plugin.deps: tuple[str, ...]` names the plugins a plugin needs. `engine/plugins/graph.py::order` returns a stable
  topological order (no edges ⇒ the order offered) and the reason each other plugin cannot load: a need that is
  missing or turned off, a need that failed, a cycle (named), a plugin listing itself.
- `run(..., required=(...))`: names the program cannot run without. A `disable` line that names one — or anything a
  required plugin needs — is ignored and logged as `plugins.required`; a required plugin that still did not load
  raises `RequiredPluginError(missing={name: why})`, which is how "no presenters ⇒ it does not start" is expressed.
- Names are unique: a second plugin with a name is refused (`duplicate plugin name`). Dependencies are resolved by
  name, so the name is the identity.
- Services: `ctx.inject(name, obj)` (same as `provide`) publishes, `ctx.service(name, kind)` / `ctx.find(...)`
  reads. With `deps` the order is guaranteed, so a plugin finds what the plugins it needs injected. What the
  object is, is for the plugins to agree on.
- The terminal passes `REQUIRED_PLUGINS = ("shell", "presenters")` (`app/plugins/loader.py`).

## Not done yet, in order

1. Make the parts real distributions with entry points: `zettcode-presenters` → plugin `presenters`; pets, themes and
   the command groups each their own plugin with `deps` (e.g. `pets` needs nothing, `/pet` command needs `pets`).
   This reverses invariant P10 (a part is never an entry point): the rule becomes "required plugins cannot be
   disabled", held by `REQUIRED_PLUGINS`, and `BUILTIN_PLUGINS` goes away. `zettcode` depends on every required one,
   so a plain install has them.
2. Present `RequiredPluginError` as a start-up message in `cli.py` (today it is an exception).
3. Shrink `app`: move `builtin_commands`, `labels`, `UsagePage`, pets out; `app` keeps the loader, the loop and the
   terminal shell.
4. `builtin_command_count` / `TuiPlugins.builtin_commands` rely on builtins loading first; with no builtins the shell
   lists commands by plugin and `/plugins` shows `required` instead of `builtins`.
5. Rewrite P10 and its tests (`test_required_plugins.py`, `test_structure.py` entry-point rule).
