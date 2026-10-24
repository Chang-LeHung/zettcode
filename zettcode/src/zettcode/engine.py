"""The engine: the one agent core that the terminal and the SDK both drive.

Most programs want :mod:`zettcode.sdk`, which is the documented, stable surface. The engine is here for the ones that
need the core itself, and it stays small on purpose; see ``docs/internal/engine.md`` for where it is going.
"""

from __future__ import annotations

from .app.agent.agent import ZettCodeAgent
from .app.agent.runtime import ZettCodeEngine

__all__ = ["ZettCodeAgent", "ZettCodeEngine"]
