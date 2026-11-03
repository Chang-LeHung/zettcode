"""The engine: the one agent core that the terminal and the SDK both drive.

Most programs want :mod:`zettcode.sdk`, which is the documented, stable surface. The engine is here for the ones that
need the core itself, and it stays small on purpose; see ``docs/internal/engine.md`` and
``docs/internal/namespace-split.md``. It imports nothing else of ours: the plugin set it runs, the line to the other
sessions and the MCP client are the SDK's, passed in by whoever builds the runtime. Names load on first use, so
importing one submodule does not build the rest.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

#: Where each public name lives; read by :func:`__getattr__` on first use.
_EXPORTS = {
    "ZettCodeEngine": ".core",
}


if TYPE_CHECKING:  # pragma: no cover - for type checkers, not the runtime
    from .core import ZettCodeEngine


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


__all__ = ["ZettCodeEngine"]
