"""The engine: the one agent core that the terminal and the SDK both drive.

Most programs want :mod:`zettcode.sdk`, which is the documented, stable surface. The engine is here for the ones that
need the core itself, and it stays small on purpose; see ``docs/internal/engine.md`` for where it is going.

Messaging between sessions is part of the core, so :mod:`zettcode.engine.messenger` lives here; the message it carries
(:mod:`zettcode.relay`) is shared with the views. Names load on first use, so importing one submodule does not build
the rest.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

#: Where each public name lives; read by :func:`__getattr__` on first use.
_EXPORTS = {
    "Messenger": ".messenger",
    "ZettCodeEngine": ".core",
}


if TYPE_CHECKING:  # pragma: no cover - for type checkers, not the runtime
    from .core import ZettCodeEngine
    from .messenger import Messenger


def __getattr__(name: str) -> object:
    """Import the module a public name lives in, the first time it is asked for."""
    try:
        module = _EXPORTS[name]
    except KeyError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
    return getattr(importlib.import_module(module, __name__), name)


def __dir__() -> list[str]:
    """Return the names this package publishes."""
    return sorted(__all__)


__all__ = ["Messenger", "ZettCodeEngine"]
