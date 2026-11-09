"""Command-line options a plugin contributes, and the values it receives back.

A plugin class may override :meth:`~zettcode.engine.plugins.plugin.Plugin.cli_arguments` with a tuple of
:class:`CliOption`. The ``zettcode`` and ``zettcode daemon spawn`` parsers read those declarations without activating
the plugin or reading a configuration, so a plugin can add a flag before the runtime exists. The parsed values are
handed back as the ``PLUGIN_CLI`` service, a mapping from the plugin's entry-point name to its own option values.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - annotations only
    import argparse
    from collections.abc import Iterable, Mapping
    from importlib.metadata import EntryPoint

#: The environment handoff used by a daemon's parent to its child; a child starts before any parser of its own.
ENV = "ZETTCODE_PLUGIN_CLI"


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

    points = tuple(entry_points) if entry_points is not None else installed_entry_points()
    found: list[tuple[str, CliOption]] = []
    for point in points:
        try:
            target = point.load()
            if not isinstance(target, type):
                continue
            declared = target.cli_arguments()  # type: ignore[attr-defined]
        except (KeyboardInterrupt, SystemExit):
            raise
        except BaseException:
            continue
        for option in declared:
            if not isinstance(option, CliOption):
                continue
            found.append((point.name, option))
    return tuple(found)


def add_options(
    parser: argparse.ArgumentParser, options: Iterable[tuple[str, CliOption]], *, prefix: str = "plugin__"
) -> tuple[tuple[str, CliOption, str], ...]:
    """Add every option with a namespace key that names its plugin, and return the keys."""
    added: list[tuple[str, CliOption, str]] = []
    for origin, option in options:
        added.append((origin, option, option.add(parser, prefix=f"{prefix}{origin}__")))
    return tuple(added)


def values(namespace: argparse.Namespace, added: Iterable[tuple[str, CliOption, str]]) -> dict[str, dict[str, object]]:
    """Return the plugin values parsed into ``namespace``, grouped by plugin."""
    result: dict[str, dict[str, object]] = {}
    for origin, option, key in added:
        result.setdefault(origin, {})[option.dest] = getattr(namespace, key)
    return result


def from_env() -> Mapping[str, Mapping[str, object]]:
    """Return the values a parent process handed a daemon through :data:`ENV`; empty when there are none."""
    raw = os.environ.get(ENV)
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except ValueError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {
        str(origin): {str(key): value for key, value in table.items()}
        for origin, table in parsed.items()
        if isinstance(table, dict)
    }


def to_env(values: Mapping[str, Mapping[str, object]]) -> str:
    """Return the environment spelling of plugin values for a daemon's child process."""
    return json.dumps({origin: dict(table) for origin, table in values.items()}, separators=(",", ":"), sort_keys=True)
