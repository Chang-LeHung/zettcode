"""Which plugins load, and which the next start leaves out.

The plugins compiled into the program always load; a plugin installed as a distribution is what a switch can leave out.
That switch is a file of names, written here and read by the loader at startup — so it is a promise about the next
process, never about the one writing it, and a front end that offers the switch has to say so.

Both the terminal's ``/plugins`` and the server's panel come through this module, so the two cannot disagree about
which names exist, which may be switched off, or where the answer is kept.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from typing import TYPE_CHECKING

from zettcode.config import read_disabled_plugins

from . import loader

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from collections.abc import Iterable, Iterator
    from contextlib import AbstractContextManager
    from importlib.metadata import EntryPoint
    from pathlib import Path

    from zettcode.config import ZettCodeConfig

    from .plugin import Plugins


@dataclass(frozen=True, slots=True)
class PluginEntry:
    """One plugin as a list of them shows it: what it is, where it came from, and whether the next start loads it.

    Attributes:
        name: What the plugin calls itself.
        origin: The distribution that carries it; the same as ``name`` for a plugin compiled into the program. This
            is the name a switch is written with, because it is the one the loader matches.
        builtin: Whether it is compiled into the program, which is what makes it impossible to switch off.
        enabled: Whether the next start loads it.
        failure: Why it could not load in this process, or ``""`` when it did.
    """

    name: str
    origin: str
    builtin: bool = False
    enabled: bool = True
    failure: str = ""


def off_names(config: ZettCodeConfig) -> tuple[str, ...]:
    """Return every name the next start will leave out, sorted: the configuration's own and the switch file's."""
    return tuple(sorted(set(config.disabled_plugins) | set(read_disabled_plugins(config.plugins_file))))


def catalog(
    config: ZettCodeConfig,
    bundle: Plugins,
    *,
    entry_points: Iterable[EntryPoint] | None = None,
) -> tuple[PluginEntry, ...]:
    """Return every plugin this installation knows, in the order a list shows them.

    That is: what loaded, builtins first as the loader takes them; then the installed distributions the next start
    will leave out; then the ones that could not load, each with the reason. A name switched off *and* failed in this
    process appears once, with both said — it is one plugin, and a list that showed it twice would be lying about how
    many there are.

    Args:
        config: Settings the switches are read from.
        bundle: What the loader produced, whose ``builtins`` is what makes a row the program's own.
        entry_points: The installed entry points; ``None`` reads the ones this environment has, so a test can pass
            its own instead of installing a distribution.
    """
    builtins = set(bundle.builtins)
    off = set(off_names(config))
    loaded = [
        PluginEntry(
            plugin.name,
            plugin.origin or plugin.name,
            builtin=(plugin.origin or plugin.name) in builtins,
            # A plugin that loaded here stays loaded here, while the switch says what the next start does.
            enabled=(plugin.origin or plugin.name) not in off,
        )
        for plugin in bundle.plugins
    ]
    failures = dict(bundle.failed)
    seen = {entry.origin for entry in loaded} | set(failures)
    points = tuple(entry_points) if entry_points is not None else loader.installed_entry_points()
    entries = list(loaded)
    for point in points:
        if point.name in seen:
            continue
        # Installed but absent from this process: the switch file left it out, or the configuration turned the whole
        # group off. Either way the next start is told the same thing, which is what `enabled` reports.
        entries.append(PluginEntry(point.name, point.name, enabled=point.name not in off))
    for origin, why in bundle.failed:
        entries.append(PluginEntry(origin, origin, builtin=origin in builtins, enabled=origin not in off, failure=why))
    return tuple(entries)


def set_enabled(
    config: ZettCodeConfig,
    name: str,
    *,
    enabled: bool,
    builtins: Iterable[str] = (),
    known: Iterable[str] = (),
) -> None:
    """Record that the next start should load ``name``, or leave it out.

    Nothing loads or unloads here: the file is read once, at startup, so this only decides what that start finds. The
    caller says what it knows — the terminal has the loaded bundle, the server has the client — and the rules below
    are the same for both.

    Args:
        config: Settings the switch file's path and the configuration's own switches come from.
        name: The plugin's origin: the distribution's entry-point name.
        enabled: True to load it next time, False to leave it out.
        builtins: The origins compiled into the program, which cannot be switched off.
        known: Every name this installation has, so a typo is refused instead of written down.

    Raises:
        ValueError: When the name is blank, is compiled into the program, is not one this installation has, is
            switched off in the configuration file, or another session holds the lock.
    """
    name = name.strip()
    if not name:
        raise ValueError("A switch needs the name of a plugin")
    if name in set(builtins):
        raise ValueError(
            f"{name} is compiled into the program, so it cannot be switched off; "
            "a plugin installed as a distribution can"
        )
    path = config.plugins_file
    written = set(read_disabled_plugins(path))
    if name not in set(known) and name not in written:
        raise ValueError(f"No plugin is called {name!r}; ask for the list to see the ones there are")
    if enabled and name in set(config.disabled_plugins):
        raise ValueError(
            f"{name} is switched off in the configuration file; remove it from [plugins] disable there, "
            "which this does not edit"
        )
    with _lock(path):
        names = set(read_disabled_plugins(path))
        if enabled:
            names.discard(name)
        else:
            names.add(name)
        _write(path, names)


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
