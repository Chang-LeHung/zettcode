"""The names objects are shared under between the runtime and the plugins, and the lookup both use.

A service is an object found by name. Two kinds travel this way:

* **What the runtime hands the plugins** before any of them activates: the state of the session that
  extensions are built on (``POLICY``, ``PERSISTENCE``, ``MODELS``, ``COMPACTION_COUNTER``,
  ``MESSENGER``, ``SELECTED_MODEL``). The runtime owns them and keeps using them itself.
* **What a plugin provides** for the rest of the application, and for the plugins loaded after it
  (``APPROVAL``, ``USAGE``, ``CONTEXT``, ``SIDES``, ``COMPACTION``, ``CAPABILITIES``, ``TODOS``).

The names are constants so that a misspelt one is an import error rather than a lookup that fails
only when the feature is first used.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from collections.abc import Mapping

#: Handed over by the runtime.
POLICY = "policy"
PERSISTENCE = "persistence"
MODELS = "models"
COMPACTION_COUNTER = "compaction-counter"
MESSENGER = "messenger"
SELECTED_MODEL = "selected-model"

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
