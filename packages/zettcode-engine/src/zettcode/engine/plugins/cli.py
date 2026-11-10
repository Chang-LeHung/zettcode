"""Command-line options a plugin contributes, and the values it receives back.

A plugin class may override :meth:`~zettcode.engine.plugins.plugin.Plugin.cli_arguments` with a tuple of
:class:`CliOption`. The ``zettcode`` and ``zettcode daemon spawn`` parsers read those declarations without activating
the plugin or reading a configuration, so a plugin can add a flag before the runtime exists. The parsed values are
handed back as the ``PLUGIN_CLI`` service, a mapping from the plugin's entry-point name to its own option values.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from zettcode.paths import DEFAULT_PLUGIN_CLI_CACHE

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from collections.abc import Iterable
    from importlib.metadata import EntryPoint


@dataclass(frozen=True, slots=True)
class CliOption:
    """One option a plugin adds to a program's command line.

    Attributes:
        flags: The spellings, such as ``("--recap-depth",)``.
        dest: The key the value is stored under for the plugin.
        help: The line ``--help`` shows.
        default: What the option takes when it is not typed.
        action: The argparse action, ``"store"``, ``"store_true"`` or ``"store_false"``.
        choices: The values argparse accepts, when the option is an enum.
        metavar: The placeholder ``--help`` shows for a value.
    """

    flags: tuple[str, ...]
    dest: str
    help: str = ""
    default: object = None
    action: str = "store"
    choices: tuple[str, ...] | None = None
    metavar: str | None = None

    def add(self, parser: argparse.ArgumentParser, *, prefix: str) -> str:
        """Add the option to ``parser`` under ``prefix`` and return the namespace key it uses."""
        key = f"{prefix}{self.dest}"
        parser.add_argument(
            *self.flags,
            dest=key,
            default=self.default,
            help=self.help,
            action=self.action,
            choices=self.choices,
            metavar=self.metavar,
        )
        return key


def installed_options(entry_points: Iterable[EntryPoint] | None = None) -> tuple[tuple[str, CliOption], ...]:
    """Return every option the installed plugin classes declare, in entry-point order.

    Loading an entry point here loads the plugin's class, not an instance: :meth:`Plugin.cli_arguments` is a class
    method precisely so this can happen before a configuration exists. An entry point that cannot be imported or
    whose declaration is malformed contributes nothing; the plugin loader reports the import failure when it loads
    the plugin for real.
    """
    from .loader import installed_entry_points
    from .plugin import Plugin

    points = tuple(entry_points) if entry_points is not None else installed_entry_points()
    found: list[tuple[str, CliOption]] = []
    for point in points:
        try:
            target = point.load()
            if not isinstance(target, type) or not issubclass(target, Plugin):
                continue
            declared = target.cli_arguments()
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            continue
        try:
            options = tuple(declared)
        except (TypeError, ValueError):
            continue
        for option in options:
            if not isinstance(option, CliOption):
                continue
            found.append((point.name, option))
    return tuple(found)


#: Format of the plugin-declaration cache. Bump when the JSON shape changes.
_CACHE_VERSION = 1
_refresh_lock = threading.Lock()
_refreshing: set[Path] = set()


def load_cached_options(path: Path | None = None, *, wait: bool = False) -> tuple[tuple[str, CliOption], ...]:
    """Return the cached declarations, or no options and a background refresh when the cache is missing or stale.

    A start must not import every installed plugin just to discover flags. The first start after installing or
    changing a plugin therefore has no new flags; the daemon thread writes them for the next start. This is
    deliberate: a restart is cheaper than paying every plugin's import cost on the interactive path.

    ``wait`` is for a non-interactive caller such as ``zettcode daemon spawn``: it collects synchronously and returns
    the fresh declarations, so a process that exits immediately cannot leave the cache empty forever.
    """
    target = path if path is not None else DEFAULT_PLUGIN_CLI_CACHE
    cached = _read_cache(target)
    if cached is not None and cached.get("version") == _CACHE_VERSION:
        # Never touch importlib.metadata or a plugin module on this path; the thread verifies the fingerprint.
        if wait:
            _refresh(target)
            refreshed = _read_cache(target)
            return _options_from_cache(refreshed) if refreshed is not None else ()
        _refresh_later(target)
        return _options_from_cache(cached)
    if wait:
        _refresh(target)
        refreshed = _read_cache(target)
        return _options_from_cache(refreshed) if refreshed is not None else ()
    _refresh_later(target)
    return ()


def _fingerprint(points: Iterable[EntryPoint]) -> list[list[str]]:
    """Return what makes the cache stale: every entry point and its module file stamp.

    The stamp sees an editable plugin whose ``cli_arguments`` changed without a version bump. Resolving the spec may
    import the module's parent package, but not the plugin module itself.
    """
    result: list[list[str]] = []
    for point in points:
        dist = getattr(getattr(point, "dist", None), "version", "") or ""
        value = str(getattr(point, "value", ""))
        module = str(getattr(point, "module", "") or value.partition(":")[0])
        origin = ""
        stamp = ""
        try:
            spec = importlib.util.find_spec(module)
            if spec is not None and spec.origin:
                origin = spec.origin
                stat = Path(origin).stat()
                stamp = f"{stat.st_mtime_ns}:{stat.st_size}"
        except Exception:
            pass
        result.append([str(getattr(point, "name", "")), value, str(dist), origin, stamp])
    return sorted(result)


def _read_cache(path: Path) -> dict[str, object] | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return None
    return raw if isinstance(raw, dict) else None


def _options_from_cache(data: dict[str, object]) -> tuple[tuple[str, CliOption], ...]:
    rows = data.get("options")
    if not isinstance(rows, list):
        return ()
    found: list[tuple[str, CliOption]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            flags = tuple(str(flag) for flag in row["flags"])
            choices = tuple(str(value) for value in row["choices"]) if row.get("choices") is not None else None
            found.append(
                (
                    str(row["origin"]),
                    CliOption(
                        flags=flags,
                        dest=str(row["dest"]),
                        help=str(row.get("help", "")),
                        default=row.get("default"),
                        action=str(row.get("action", "store")),
                        choices=choices,
                        metavar=row.get("metavar"),
                    ),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return tuple(found)


def _refresh_later(target: Path) -> None:
    """Refresh the cache on a daemon thread, once per process and cache path."""
    with _refresh_lock:
        if target in _refreshing:
            return
        _refreshing.add(target)
    thread = threading.Thread(
        target=_refresh,
        args=(target, 0.5),
        name="zettcode-plugin-cli-cache",
        daemon=True,
    )
    thread.start()


def _refresh(target: Path, delay: float = 0.0) -> None:
    try:
        if delay:
            # Let the first frame paint before importing a tree of plugin modules in this process.
            time.sleep(delay)
        from .loader import installed_entry_points

        points = tuple(installed_entry_points())
        fingerprint = _fingerprint(points)
        cached = _read_cache(target)
        if cached is not None and cached.get("version") == _CACHE_VERSION and cached.get("fingerprint") == fingerprint:
            return
        rows: list[dict[str, object]] = []
        for origin, option in installed_options(points):
            try:
                json.dumps(option.default)
            except (TypeError, ValueError):
                continue
            rows.append(
                {
                    "origin": origin,
                    "flags": list(option.flags),
                    "dest": option.dest,
                    "help": option.help,
                    "default": option.default,
                    "action": option.action,
                    "choices": list(option.choices) if option.choices is not None else None,
                    "metavar": option.metavar,
                }
            )
        _write_cache(target, {"version": _CACHE_VERSION, "fingerprint": fingerprint, "options": rows})
    except Exception as error:
        # The next start tries again; a cache miss is already an accepted outcome, but say why once.
        sys.stderr.write(f"zettcode: could not cache plugin CLI options: {error}\n")
    finally:
        with _refresh_lock:
            _refreshing.discard(target)


def _write_cache(path: Path, data: dict[str, object]) -> None:
    """Write the cache atomically, so a concurrent start sees either the old file or the new one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # A killed writer leaves a temp file behind; remove old ones when the next write runs.
    for stale in path.parent.glob(f".{path.name}.*.tmp"):
        try:
            if time.time() - stale.stat().st_mtime > 3600:
                stale.unlink()
        except OSError:
            pass
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        temporary.write_text(json.dumps(data, separators=(",", ":"), sort_keys=True), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except OSError:
            pass


def add_options(
    parser: argparse.ArgumentParser, options: Iterable[tuple[str, CliOption]], *, prefix: str = "plugin__"
) -> tuple[tuple[str, CliOption, str], ...]:
    """Add every option with a namespace key that names its plugin, and return the keys.

    A colliding flag or a default that cannot cross a daemon's JSON handoff drops only that option and names it on
    stderr; one bad plugin declaration must not make every start a traceback.
    """
    added: list[tuple[str, CliOption, str]] = []
    for origin, option in options:
        if (
            not isinstance(option.flags, tuple)
            or not option.flags
            or not all(isinstance(flag, str) and flag.startswith("-") for flag in option.flags)
        ):
            print(f"zettcode: ignored {origin} {option.dest!r}: flags must be option strings", file=sys.stderr)
            continue
        if not isinstance(option.dest, str) or not option.dest.strip():
            print(f"zettcode: ignored {origin} {option.flags[0]}: a destination is required", file=sys.stderr)
            continue
        label = option.flags[0]
        try:
            json.dumps(option.default)
        except (TypeError, ValueError):
            print(f"zettcode: ignored {origin} {label}: its default is not JSON-safe", file=sys.stderr)
            continue
        try:
            key = option.add(parser, prefix=f"{prefix}{origin}__")
        except (argparse.ArgumentError, TypeError, ValueError) as error:
            print(f"zettcode: ignored {origin} {label}: {error}", file=sys.stderr)
            continue
        added.append((origin, option, key))
    return tuple(added)


def values(namespace: argparse.Namespace, added: Iterable[tuple[str, CliOption, str]]) -> dict[str, dict[str, object]]:
    """Return the plugin values parsed into ``namespace``, grouped by plugin."""
    result: dict[str, dict[str, object]] = {}
    for origin, option, key in added:
        result.setdefault(origin, {})[option.dest] = getattr(namespace, key)
    return result
