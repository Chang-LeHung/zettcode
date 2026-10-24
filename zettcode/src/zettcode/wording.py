"""Words the engine and the views both say, so neither has to import the other to agree on them.

A leaf with no imports, shared like :mod:`zettcode.budget`, :mod:`zettcode.statusline` and :mod:`zettcode.providers`.
"""

from __future__ import annotations

__all__ = ["UNTITLED_SESSION"]

#: The name a session shows before the agent has given it a title.
UNTITLED_SESSION = "New session"
