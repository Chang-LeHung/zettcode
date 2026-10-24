"""What every part of the agent shares: the runtime it speaks to, and who and where it is.

The mixins in this package are split by what they are responsible for, and each one
inherits this class only to be type-checked against what the others rely on. The two
properties here are read by nearly all of them, which is why they live below all of them.
"""

from __future__ import annotations

from pathlib import Path

from zettcode.engine.core import ZettCodeEngine
from zettcode.engine.dialogue.mentions import MentionProvider
from zettcode.engine.storage import SessionLocked


class AgentBase:
    """The runtime, the workspace it works in, and the session the next turn belongs to."""

    #: The runtime this agent speaks to; the one thing the application agent holds.
    runtime: ZettCodeEngine

    @property
    def workspace(self) -> Path:
        """Return the workspace displayed in the header."""
        return self.runtime.config.workspace

    @property
    def session_id(self) -> str:
        """Return the session used for the next turn."""
        return self.runtime.session_id

    @property
    def plugin_mentions(self) -> tuple[MentionProvider, ...]:
        """Return the ``@`` resource providers the installed plugins registered."""
        return self.runtime.plugins.mentions

    @property
    def session_locked(self) -> bool:
        """Return whether another process has the active session open, so that this one may only read it.

        Every session is locked by the process that has it open (see :mod:`..storage.locks`). A session this
        process started is always its own; one it resumed may be somebody else's, and then it is shown and
        nothing is written to it: no turn, no title, no compaction.
        """
        return self.runtime.session_locked

    def retake_session(self) -> bool:
        """Try again to lock the active session; return whether this process holds it now."""
        return self.runtime.retake_session()

    def require_session(self) -> None:
        """Refuse to go on when the active session is another process's.

        Raises:
            SessionLocked: The lock is not held. A ``ValueError``, which the shell shows as a line in the
                conversation.
        """
        if self.session_locked:
            raise SessionLocked()
