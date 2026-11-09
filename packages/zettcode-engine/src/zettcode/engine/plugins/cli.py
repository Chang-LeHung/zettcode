"""Command-line options a plugin contributes, and the values it receives back.

A plugin class may override :meth:`~zettcode.engine.plugins.plugin.Plugin.cli_arguments` with a tuple of
:class:`CliOption`. The ``zettcode`` and ``zettcode daemon spawn`` parsers read those declarations without activating
the plugin or reading a configuration, so a plugin can add a flag before the runtime exists. The parsed values are
handed back as the ``PLUGIN_CLI`` service, a mapping from the plugin's entry-point name to its own option values.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING

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
