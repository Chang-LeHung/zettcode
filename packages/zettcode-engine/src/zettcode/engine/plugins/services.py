"""The names objects are shared under between the runtime and the plugins, and the lookup both use.

A service is an object found by name. Two kinds travel this way:

* **What the runtime hands the plugins** before any of them activates: the state of the session that
  extensions are built on (``POLICY``, ``PERSISTENCE``, ``SESSION_STORE``, ``USAGE_LEDGER``, ``MODELS``,
  ``COMPACTION_COUNTER``, ``SELECTED_MODEL``). The runtime owns them and keeps using them itself.
* **What a front end hands the plugins** through ``ZettCodeEngine.preview(shared=...)``: an object the
  engine cannot build and does not use, such as the line to the other sessions. The name is the
  front end's and the plugin's to agree on; the engine only passes the mapping through.
* **What a plugin provides** for the rest of the application, and for the plugins loaded after it
  (``APPROVAL``, ``USAGE``, ``CONTEXT``, ``SIDES``, ``COMPACTION``, ``CAPABILITIES``, ``TODOS``).

The names are constants so that a misspelt one is an import error rather than a lookup that fails
only when the feature is first used.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

from zettcode.engine.service_contracts import CONTEXT_REPORT, SESSION_STORE, USAGE_LEDGER

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from collections.abc import Mapping

#: Handed over by the runtime.
POLICY = "policy"
HARNESS = "harness"
PERSISTENCE = "persistence"
MODELS = "models"
COMPACTION_COUNTER = "compaction-counter"
SELECTED_MODEL = "selected-model"

#: What the plugin context gives a plugin: the same values its attributes expose, found by name.
PLUGIN_AGENT = "plugin-agent"
PLUGIN_COMMANDS = "plugin-commands"
PLUGIN_TUI = "plugin-tui"
PLUGIN_CONFIG = "plugin-config"
PLUGIN_WORKSPACE = "plugin-workspace"
PLUGIN_SETTINGS = "plugin-settings"

#: Provided by the built-in plugins.
APPROVAL = "approval"
USAGE = "usage"
CONTEXT = "context"
SIDES = "sides"
COMPACTION = "compaction"
CAPABILITIES = "capabilities"
TODOS = "todos"

_T = TypeVar("_T")


def lookup(services: Mapping[str, object], name: str, kind: type[_T]) -> _T | None:
    """Return the service called ``name`` as a ``kind``, or ``None`` when nobody provides it.

    Raises:
        TypeError: When the name is taken by an object of another type; that is a plugin bug, not an
            absence, and hiding it as ``None`` would send the search somewhere else.
    """
    if name not in services:
        return None
    found = services[name]
    if not isinstance(found, kind):
        raise TypeError(f"Service {name!r} is a {type(found).__name__}, not a {kind.__name__}")
    return found


def require(services: Mapping[str, object], name: str, kind: type[_T]) -> _T:
    """Return the service called ``name`` as a ``kind``.

    Raises:
        LookupError: When nobody provides it; the message names the service.
        TypeError: When the name is taken by an object of another type.
    """
    found = lookup(services, name, kind)
    if found is None:
        raise LookupError(f"No plugin provides the {name!r} service")
    return found


__all__ = [
    "CONTEXT_REPORT",
    "PLUGIN_AGENT",
    "PLUGIN_COMMANDS",
    "PLUGIN_CONFIG",
    "PLUGIN_SETTINGS",
    "PLUGIN_TUI",
    "PLUGIN_WORKSPACE",
    "SESSION_STORE",
    "USAGE_LEDGER",
    "lookup",
    "require",
]
