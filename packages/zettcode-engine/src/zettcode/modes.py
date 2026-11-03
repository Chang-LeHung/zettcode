"""How a message asks to be handled by a recipient that is busy with a request.

A leaf with no imports, so the broker, the SDK, the server and the shell can name the two modes without one of them
depending on another. The broker's protocol re-exports these names, because that is where they are checked; an
unknown value is refused there, and a missing one means :data:`MODE_STEER`.
"""

from __future__ import annotations

#: Hand the message to the request that is running, so it changes course.
MODE_STEER = "steer"

#: Wait until the request that is running ends.
MODE_FOLLOWUP = "followup"

MODES = (MODE_STEER, MODE_FOLLOWUP)

__all__ = ["MODE_FOLLOWUP", "MODE_STEER", "MODES"]
