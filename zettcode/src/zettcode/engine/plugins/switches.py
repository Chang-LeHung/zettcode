"""Which plugins load, and which the next start leaves out.

Two things decide it, and both are written now for the process that starts next:

* A plugin installed as a distribution is switched by a file of names beside the session store.
* A plugin compiled into the program has no file of its own. What turns its work off is a setting the reader already
  has — ``[skills] enabled``, ``[mcp] enabled`` — which the plugin declares (see
  :attr:`~zettcode.engine.plugins.plugin.Plugin.setting`). A compiled-in plugin that declares none cannot be switched
  at all, so :func:`catalog` leaves it out rather than list a row with nothing to press.

The terminal's ``/plugins`` page, the server's panel and the SDK all come through this module, so they cannot disagree
about which names exist, which may be switched, or where the answer is kept.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING

from zettcode.config import read_disabled_plugins
from zettcode.config_edit import ConfigEditError, set_boolean, write_text_atomically
from zettcode.paths import config_path

from . import loader

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from collections.abc import Iterable, Iterator, Mapping
    from contextlib import AbstractContextManager
    from importlib.metadata import EntryPoint

    from zettcode.config import ZettCodeConfig

    from .plugin import Plugins, PluginSetting


@dataclass(frozen=True, slots=True)
class PluginEntry:
    """One plugin as a list of them shows it: what it is, where it came from, and whether the next start loads it.

    Attributes:
        name: What the plugin calls itself.
        origin: The distribution that carries it; the same as ``name`` for a plugin compiled into the program. This
            is the name a switch is written with, because it is the one the loader matches.
        builtin: Whether it is compiled into the program.
        enabled: Whether the next start does its work.
        failure: Why it could not load in this process, or ``""`` when it did.
        setting: The configuration key that decides a compiled-in plugin (``"skills.enabled"``); empty for an
            installed one, which the switch file holds.
        switchable: Whether there is anything a reader can do about it *here*. A compiled-in plugin that failed has no
            switch, and neither has one whose switch belongs to a line the reader wrote; a list draws those rows
            without one, and says why in ``why``.
        why: Why it cannot be switched, when it cannot; empty otherwise.
    """

    name: str
    origin: str
    builtin: bool = False
    enabled: bool = True
    failure: str = ""
    setting: str = ""
    switchable: bool = True
    why: str = ""


@dataclass(frozen=True, slots=True)
class SwitchState:
    """What writing an installed plugin's switch needs, for a caller that did not build the whole settings object."""

    plugins_file: Path
    plugins_enabled: bool = True
    disabled_plugins: tuple[str, ...] = ()


def off_names(config: ZettCodeConfig) -> tuple[str, ...]:
    """Return every name the next start will leave out, sorted: the configuration's own and the switch file's."""
    return tuple(sorted(set(config.disabled_plugins) | set(read_disabled_plugins(config.plugins_file))))


def held_by_config(config: ZettCodeConfig) -> frozenset[str]:
    """Return the names the *configuration file* switches off — the lines neither front end may edit.

    ``ZettCodeConfig.disabled_plugins`` is that list alone; the switch file's names are read here, so a name in both
    places is still the configuration's: a set difference would call it the switch file's and let a page offer a
    switch that the configuration goes on overriding.
    """
    return frozenset(config.disabled_plugins)


def catalog(
    config: ZettCodeConfig,
    bundle: Plugins,
    *,
    entry_points: Iterable[EntryPoint] | None = None,
) -> tuple[PluginEntry, ...]:
    """Return every plugin a list can show, in the order it shows them.

    That is: the compiled-in plugins the reader can switch, each with the setting that decides it; the installed
    distributions, in load order, with the ones the next start leaves out; then the ones that could not load, each
    with the reason. A compiled-in plugin with no setting is not here at all: there is nothing a reader could do about
    it.

    Args:
        config: Settings the switches are read from.
        bundle: What the loader produced, whose ``builtins`` says which rows are the program's own.
        entry_points: The installed entry points; ``None`` reads the ones this environment has, so a test can pass
            its own instead of installing a distribution.
    """
    builtins = set(bundle.builtins)
    off = set(off_names(config))
    held = held_by_config(config)
    compiled: list[PluginEntry] = []
    installed: list[PluginEntry] = []
    for plugin in bundle.plugins:
        origin = plugin.origin or plugin.name
        setting = plugin.setting
        if origin in builtins:
            if setting is not None:
                compiled.append(
                    PluginEntry(
                        plugin.name,
                        origin,
                        builtin=True,
                        enabled=bool(getattr(config, setting.field)),
                        setting=setting.path,
                    )
                )
            continue
        installed.append(_installed(plugin.name, origin, config, off=off, held=held))
    points = tuple(entry_points) if entry_points is not None else loader.installed_entry_points()
    seen = {entry.origin for entry in installed} | {origin for origin, _why in bundle.failed}
    for point in points:
        if point.name not in seen:
            installed.append(_installed(point.name, point.name, config, off=off, held=held))
    # A single-file plugin that is switched off is not in the bundle (the loader never imported it), so the folder is
    # what says it exists: it stays on the page, off, where it can be switched back on.
    for path in loader.installed_files(config.plugins_dir):
        if path.stem not in seen:
            installed.append(_installed(path.stem, path.stem, config, off=off, held=held))
    failed = [
        _failed(origin, why, config, builtin=origin in builtins, off=off, held=held) for origin, why in bundle.failed
    ]
    # The group a row belongs to decides where it stands, so a group is one run of rows and gets one heading.
    return tuple(
        [
            *compiled,
            *(entry for entry in failed if entry.builtin),
            *installed,
            *(entry for entry in failed if not entry.builtin),
        ]
    )


def _installed(name: str, origin: str, config: ZettCodeConfig, *, off: set[str], held: frozenset[str]) -> PluginEntry:
    """Return one installed plugin's row: whether the next start loads it, and whether its switch can move."""
    if not config.plugins_enabled:
        why = "installed plugins are off entirely: [plugins] enabled = false in the configuration file"
    elif origin in held:
        why = "switched off in the configuration file; remove it from [plugins] disable there"
    else:
        why = ""
    return PluginEntry(
        name,
        origin,
        enabled=config.plugins_enabled and origin not in off,
        switchable=why == "",
        why=why,
    )


def _failed(
    origin: str, why: str, config: ZettCodeConfig, *, builtin: bool, off: set[str], held: frozenset[str]
) -> PluginEntry:
    """Return the row of a plugin that could not load.

    A compiled-in one has no switch here: the object that declares its setting never loaded. An installed one keeps
    its: the switch file is exactly what would leave it out next time, and its row says both things.
    """
    if builtin:
        return PluginEntry(
            origin,
            origin,
            builtin=True,
            enabled=origin not in off,
            failure=why,
            switchable=False,
            why="it could not load, so there is no switch to move",
        )
    row = _installed(origin, origin, config, off=off, held=held)
    return PluginEntry(
        row.name,
        row.origin,
        enabled=row.enabled,
        failure=why,
        switchable=row.switchable,
        why=row.why,
    )


def set_many(
    config: ZettCodeConfig,
    changes: Mapping[str, bool],
    *,
    bundle: Plugins,
    entry_points: Iterable[EntryPoint] | None = None,
) -> tuple[dict[str, bool], list[tuple[PluginSetting, bool]], list[str]]:
    """Write every switch down, each file once, and say what was written and what was refused.

    A plugin compiled into the program is one key of the configuration file; every such change goes into one read, one
    edit and one replace. An installed plugin is a name in the switch file, and those go in one write under the lock.
    A name that cannot be written is reported and the rest still are, so a panel's Enter is not undone by one refusal.

    Everything the rules need comes from the bundle and the configuration — which names exist, which are compiled in,
    which declare a setting, which the configuration file holds, which group is off — so a front end that has those
    two cannot apply a different rule from another one.

    Nothing loads or unloads here: both files are read once, at startup, so this only decides what that start finds.

    Args:
        config: Settings the switch file's path, the configuration's own lists and the file's location come from.
        changes: The plugin's name or origin to the state to write for it.
        bundle: What the loader produced: the names, the origins and the settings.
        entry_points: The installed entry points; ``None`` reads the ones this environment has.

    Returns:
        The origins written and their state, the configuration keys written (for a caller keeping one in memory), and
        one message per name that could not be written.
    """
    written: dict[str, bool] = {}
    keys: list[tuple[PluginSetting, bool]] = []
    problems: list[str] = []
    settings, builtins, known = _rules(config, bundle, entry_points)
    key_changes: list[tuple[str, PluginSetting, bool]] = []
    file_changes: dict[str, bool] = {}
    off = set(read_disabled_plugins(config.plugins_file))
    held = held_by_config(config)
    for asked, enabled in changes.items():
        asked = asked.strip()
        if not asked:
            problems.append("A switch needs the name of a plugin")
            continue
        # A switch is written with the distribution's name; a plugin that calls itself something else is reached by
        # either, and written with the one the loader matches.
        name = known.get(asked, asked)
        setting = settings.get(name)
        if setting is not None:
            key_changes.append((name, setting, enabled))
            continue
        if name in builtins:
            if name in {origin for origin, _why in bundle.failed}:
                problems.append(
                    f"{name} could not load, so the setting that switches it is not known here; "
                    "edit the configuration file to leave it out"
                )
            else:
                problems.append(
                    f"{name} is compiled into the program and has no setting of its own, so it cannot be switched"
                )
            continue
        if name not in known and name not in off:
            problems.append(f"No plugin is called {asked!r}; ask for the list to see the ones there are")
            continue
        if enabled and name in held:
            problems.append(
                f"{name} is switched off in the configuration file; remove it from [plugins] disable there, "
                "which this does not edit"
            )
            continue
        if not config.plugins_enabled:
            problems.append(
                f"{name} is switched by [plugins] enabled = false in the configuration file, which turns every "
                "installed plugin off; edit that line to load them again"
            )
            continue
        file_changes[name] = enabled
        written[name] = enabled
    # The switch file first: it is the cheaper write, and a lock somebody else holds is the likelier refusal, so a
    # batch that fails there fails before the configuration file is touched.
    if file_changes:
        try:
            with _lock(config.plugins_file):
                names = set(read_disabled_plugins(config.plugins_file))
                for name, enabled in file_changes.items():
                    names.discard(name) if enabled else names.add(name)
                _write(config.plugins_file, names)
        except (OSError, ValueError) as error:
            # Nothing of this batch was written, so the refusals above are still worth reporting with it.
            return {}, [], [*problems, f"the plugin switch file could not be written: {error}"]
        written.update(file_changes)
    if key_changes:
        keys = [(setting, enabled) for _name, setting, enabled in key_changes]
        try:
            _write_settings(config, keys)
        except ValueError as error:
            # The switch file's names are in that file; say which, so a reader is not left guessing what landed.
            landed = ", ".join(f"{name} {'on' if enabled else 'off'}" for name, enabled in written.items())
            note = str(error) if not written else f"{error} (already written to the switch file: {landed})"
            return written, [], [*problems, note]
        written.update({name: enabled for name, _setting, enabled in key_changes})
    return written, keys, problems


def _rules(
    config: ZettCodeConfig, bundle: Plugins, entry_points: Iterable[EntryPoint] | None = None
) -> tuple[dict[str, PluginSetting], set[str], dict[str, str]]:
    """Return what a switch needs: the settings by origin, the origins compiled in, and every name to its origin.

    A plugin may call itself something other than the distribution's name; both reach it, and both are written with the
    origin, because that is the name the loader matches.
    """
    builtins = set(bundle.builtins)
    settings = {
        plugin.origin or plugin.name: plugin.setting
        for plugin in bundle.plugins
        if plugin.setting is not None and (plugin.origin or plugin.name) in builtins
    }
    points = tuple(entry_points) if entry_points is not None else loader.installed_entry_points()
    known: dict[str, str] = {}
    # Every origin first — a distribution's, a compiled-in plugin's, a switched-off name's — because a plugin that
    # calls itself one of those must not take it over: the page's switch for that name would write the plugin's
    # origin instead, and leave the distribution it meant switched off.
    for plugin in bundle.plugins:
        origin = plugin.origin or plugin.name
        known[origin] = origin
    for name in (*builtins, *(point.name for point in points)):
        known[name] = name
    for path in loader.installed_files(config.plugins_dir):
        known[path.stem] = path.stem
    for name in (*read_disabled_plugins(config.plugins_file), *config.disabled_plugins):
        known[name] = name
    for plugin in bundle.plugins:
        known.setdefault(plugin.name, plugin.origin or plugin.name)
    return settings, builtins, known


def set_enabled(
    config: ZettCodeConfig,
    name: str,
    *,
    enabled: bool,
    bundle: Plugins,
    entry_points: Iterable[EntryPoint] | None = None,
) -> PluginSetting | None:
    """Write one switch down, and return the configuration key it went to when that is where it went.

    The rules are :func:`set_many`'s; this one raises instead of collecting, because a caller that asked for a single
    name wants to hear why it could not be written.

    Raises:
        ValueError: When the name cannot be written, or its file cannot.
    """
    _, keys, problems = set_many(config, {name: enabled}, bundle=bundle, entry_points=entry_points)
    if problems:
        raise ValueError(problems[0])
    return keys[0][0] if keys else None


def applied(config: ZettCodeConfig, setting: PluginSetting, enabled: bool) -> ZettCodeConfig:
    """Return ``config`` with the field a switch wrote updated, so this process shows what it decided."""
    # The field name is a string the plugin declared, and its type is a bool, which no signature can say.
    return replace(config, **{setting.field: enabled})  # type: ignore[arg-type]


def set_installed(config: ZettCodeConfig | SwitchState, name: str, *, enabled: bool) -> None:
    """Write one installed plugin's switch to the switch file, without loading any plugin.

    A management command asks this for a name it has already checked exists (an entry point, a single file in
    :attr:`ZettCodeConfig.plugins_dir`, or a name the file already holds). It follows the same rules a panel does:
    nothing is written while ``[plugins] enabled`` is off, and a name the configuration file holds stays the
    configuration's.

    Raises:
        ValueError: When the name cannot be written there, or the file cannot be.
    """
    name = name.strip()
    if not name:
        raise ValueError("A switch needs the name of a plugin")
    if not config.plugins_enabled:
        raise ValueError(
            "[plugins] enabled = false in the configuration file turns every installed plugin off; edit that line "
            "to load them again"
        )
    if enabled and name in config.disabled_plugins:
        raise ValueError(
            f"{name} is switched off in the configuration file; remove it from [plugins] disable there, which this "
            "does not edit"
        )
    try:
        with _lock(config.plugins_file):
            names = set(read_disabled_plugins(config.plugins_file))
            names.discard(name) if enabled else names.add(name)
            _write(config.plugins_file, names)
    except (OSError, ValueError) as error:
        raise ValueError(f"the plugin switch file could not be written: {error}") from error


def forget_installed(config: ZettCodeConfig | SwitchState, name: str) -> bool:
    """Drop ``name`` from the switch file if it is there, and say whether it was.

    An uninstall calls this: a name left behind by a plugin that is gone would make a later install of the same name
    start switched off, with nothing left to explain why. There is no policy to apply — the name is being retired,
    not switched — so this does not consult the configuration's own list.
    """
    name = name.strip()
    if not name:
        return False
    try:
        with _lock(config.plugins_file):
            names = set(read_disabled_plugins(config.plugins_file))
            if name not in names:
                return False
            names.discard(name)
            _write(config.plugins_file, names)
    except (OSError, ValueError):
        return False
    return True


def _write_settings(config: ZettCodeConfig, keys: list[tuple[PluginSetting, bool]]) -> None:
    """Write every configuration key in one pass over one file.

    The file is the one the other settings are written to (:func:`zettcode.paths.config_path`), so a switch made here
    lands where ``/theme`` and ``/statusline`` put theirs.

    Raises:
        ValueError: When there is no configuration file to write, or one of the keys cannot be edited.
    """
    path = config_path()
    if not path.is_file():
        names = ", ".join(sorted(setting.path for setting, _ in keys))
        raise ValueError(
            f"{names} in the configuration file decides this, and there is none at {path} to write; create one first"
        )
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ValueError(f"{path} could not be read: {error}") from error
    try:
        for setting, enabled in keys:
            text = set_boolean(text, setting.table, setting.key, enabled, where=path, command="/plugins")
        write_text_atomically(path, text)
    except (ConfigEditError, OSError) as error:
        raise ValueError(str(error)) from error


def _lock(path: Path) -> AbstractContextManager[object]:
    """Serialise a read-modify-write of the switch file between two sessions running at once."""
    from contextlib import contextmanager

    from zettcode.filelock import SingletonLock

    @contextmanager
    def held() -> Iterator[None]:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        lock = SingletonLock(path.with_suffix(".lock"))
        if not lock.acquire(wait=2.0):
            raise ValueError("another session is changing the plugin switches; try again in a moment")
        try:
            yield None
        finally:
            lock.release()

    return held()


def _write(path: Path, names: Iterable[str]) -> None:
    """Write the switch file in one replace, owner-only, so a crash cannot leave half a list."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=".plugins-", suffix=".json")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump({"disabled": sorted(names)}, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
