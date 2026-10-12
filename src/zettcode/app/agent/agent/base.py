"""What every part of the agent shares: the runtime it speaks to, and who and where it is.

The mixins in this package are split by what they are responsible for, and each one
inherits this class only to be type-checked against what the others rely on. The two
properties here are read by nearly all of them, which is why they live below all of them.
"""

from __future__ import annotations

from pathlib import Path

from ..runtime import ZettCodeRuntime


class AgentBase:
    """The runtime, the workspace it works in, and the session the next turn belongs to."""

    #: The runtime this agent speaks to; the one thing the application agent holds.
    runtime: ZettCodeRuntime

    @property
    def workspace(self) -> Path:
        """Return the workspace displayed in the header."""
        return self.runtime.config.workspace

    @property
    def session_id(self) -> str:
        """Return the session used for the next turn."""
        return self.runtime.session_id
